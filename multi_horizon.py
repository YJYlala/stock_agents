"""Multi-Horizon Orchestrator — runs SHORT / MID / LONG teams in parallel.

Each horizon team uses:
  - Same data (pre-fetched once)
  - Different quant engine weights
  - Different prompt preambles
  - Different risk parameters
  - Different decision thresholds

Results are combined into a MultiHorizonDecision with a consensus view.
"""

import asyncio
import logging

from stock_agents.agents.fund_manager import FundManager
from stock_agents.agents.fundamental_analyst import FundamentalAnalyst
from stock_agents.agents.quant_trader import QuantTrader
from stock_agents.agents.research_bear import BearResearcher
from stock_agents.agents.research_bull import BullResearcher
from stock_agents.agents.risk_manager import RiskManager
from stock_agents.agents.sentiment_analyst import SentimentAnalyst
from stock_agents.agents.technical_analyst import TechnicalAnalyst
from stock_agents.config.horizons import (
    ALL_HORIZONS,
    Horizon,
    HorizonConfig,
    get_horizon_config,
)
from stock_agents.config.prompts import get_horizon_prompt
from stock_agents.config.settings import Settings
from stock_agents.data.data_manager import DataManager
from stock_agents.indicators.quant_engine import run_quant_pipeline
from stock_agents.models.signals import (
    AgentReport,
    DebateReport,
    FinalDecision,
    MultiHorizonDecision,
)
from stock_agents.orchestrator import TradingOrchestrator

logger = logging.getLogger(__name__)


class _HorizonAgent:
    """Wraps a BaseAgent with horizon-specific prompt override."""

    def __init__(self, agent, horizon_config: HorizonConfig, agent_type: str):
        self._agent = agent
        self._horizon_prompt = get_horizon_prompt(agent_type, horizon_config)

    def get_system_prompt(self) -> str:
        return self._horizon_prompt

    def gather_data(self, symbol, context=None):
        return self._agent.gather_data(symbol, context)

    def analyze(self, symbol, context=None):
        # Temporarily replace the prompt
        original_prompt_fn = self._agent.get_system_prompt
        self._agent.get_system_prompt = self.get_system_prompt
        try:
            return self._agent.analyze(symbol, context)
        finally:
            self._agent.get_system_prompt = original_prompt_fn

    async def analyze_async(self, symbol, context=None):
        return await asyncio.to_thread(self.analyze, symbol, context)

    @property
    def name(self):
        return self._agent.name

    @property
    def role(self):
        return self._agent.role


class _HorizonFundManager:
    """Wraps FundManager with horizon-specific prompt."""

    def __init__(self, fund_manager: FundManager, horizon_config: HorizonConfig):
        self._fm = fund_manager
        self._horizon_prompt = get_horizon_prompt("fund_manager", horizon_config)
        self._horizon_config = horizon_config

    def decide(self, symbol, agent_reports, debate_report=None,
               trade_history=None, quant_signals=None):
        from stock_agents.config.prompts import FUND_MANAGER
        # Monkey-patch the prompt module temporarily
        import stock_agents.config.prompts as prompts_mod
        original = prompts_mod.FUND_MANAGER
        prompts_mod.FUND_MANAGER = self._horizon_prompt
        try:
            decision = self._fm.decide(
                symbol, agent_reports, debate_report, trade_history, quant_signals
            )
            decision.horizon = self._horizon_config.horizon.value
            decision.horizon_label = self._horizon_config.label_cn
            return decision
        finally:
            prompts_mod.FUND_MANAGER = original


class MultiHorizonOrchestrator:
    """Runs 3 horizon teams for each stock, producing a MultiHorizonDecision."""

    def __init__(self, settings: Settings, account_client=None,
                 horizons: list[Horizon] | None = None):
        self.settings = settings
        self.data = DataManager(settings, account_client=account_client)
        self.horizons = horizons or ALL_HORIZONS

        # Build LLM clients (shared across all horizons — same model)
        self.llm = TradingOrchestrator._build_llm(settings, settings.llm.model)
        self.llm_final = TradingOrchestrator._build_llm(settings, settings.llm.model_final)

        # Rate-limit semaphore: only 1 concurrent LLM call to avoid 429
        self._llm_semaphore = asyncio.Semaphore(1)

        # Base agents (will be wrapped per-horizon)
        self._base_agents = {
            "fundamental": FundamentalAnalyst(self.llm, self.data),
            "technical": TechnicalAnalyst(self.llm, self.data),
            "sentiment": SentimentAnalyst(self.llm, self.data),
            "bull": BullResearcher(self.llm, self.data),
            "bear": BearResearcher(self.llm, self.data),
            "quant": QuantTrader(self.llm, self.data),
            "risk": RiskManager(self.llm, self.data),
        }
        self._base_fund_manager = FundManager(self.llm_final, self.data)

    def _build_quant_data(self, symbol: str) -> dict:
        """Collect raw data needed by the quant engine."""
        snapshot = self.data.get_stock_snapshot(symbol)
        financials = self.data.get_financial_data(symbol)
        indicators = self.data.get_technical_indicators(symbol)
        risk_metrics = self.data.get_risk_metrics(symbol)
        portfolio = self.data.get_portfolio_state()

        ind_dict = indicators.model_dump() if hasattr(indicators, "model_dump") else {}
        fin_dict = {
            "pe_ratio": snapshot.pe_ratio,
            "pb_ratio": snapshot.pb_ratio,
            "roe": financials.roe,
            "gross_margin": financials.gross_margin,
            "net_margin": financials.net_margin,
            "revenue_growth": financials.revenue_growth,
            "profit_growth": financials.profit_growth,
            "debt_to_equity": financials.debt_to_equity,
            "operating_cash_flow": financials.operating_cash_flow,
            "net_profit": financials.net_profit,
            "eps": financials.eps,
        }
        positions_data = [
            {"symbol": pos.symbol, "weight_pct": pos.weight_pct}
            for pos in portfolio.positions
        ]

        return {
            "indicators": ind_dict,
            "financials": fin_dict,
            "risk_metrics": risk_metrics,
            "current_price": snapshot.current_price,
            "market_cap": snapshot.market_cap,
            "portfolio_value": portfolio.total_value,
            "portfolio_positions": positions_data,
            "atr": indicators.atr_14,
        }

    def _run_quant_for_horizon(self, quant_data: dict, hcfg: HorizonConfig) -> dict:
        """Run quant engine with horizon-specific parameters."""
        weights = {
            "fundamental": hcfg.weight_fundamental,
            "technical": hcfg.weight_technical,
            "growth": hcfg.weight_growth,
            "risk": hcfg.weight_risk,
        }
        risk_limits = {
            "max_single_position_pct": hcfg.max_position_pct,
            "max_sector_pct": self.settings.risk.max_sector_pct,
            "max_drawdown_pct": hcfg.max_drawdown_pct,
        }
        return run_quant_pipeline(
            **{k: v for k, v in quant_data.items() if k != "atr"},
            atr=quant_data["atr"],
            risk_limits=risk_limits,
            horizon_weights=weights,
            kelly_cap=hcfg.kelly_fraction_cap,
            hold_period_days=hcfg.hold_period_days,
            stop_loss_atr_mult=hcfg.stop_loss_atr_mult,
            buy_threshold=hcfg.buy_threshold,
            sell_threshold=hcfg.sell_threshold,
        )

    async def _run_single_horizon(
        self, symbol: str, horizon: Horizon, quant_data: dict,
        portfolio_context: dict, trade_history: list,
    ) -> FinalDecision:
        """Run the full 5-phase pipeline for one horizon."""
        hcfg = get_horizon_config(horizon)
        tag = f"[{hcfg.label_cn}]"
        logger.info("  %s Starting %s team...", tag, hcfg.label)

        # Run horizon-specific quant engine
        quant_signals = await asyncio.to_thread(
            self._run_quant_for_horizon, quant_data, hcfg
        )
        qs = quant_signals.get("quant_signal", {})
        logger.info("  %s QuantEngine: composite=%.2f signal=%s kelly=%.4f",
                     tag, qs.get("composite_score", 0),
                     qs.get("signal", "N/A"), qs.get("kelly_fraction", 0))

        ctx = {
            **portfolio_context,
            "quant_signals": quant_signals,
        }

        # Create horizon-wrapped agents
        agents = {
            name: _HorizonAgent(agent, hcfg, name)
            for name, agent in self._base_agents.items()
        }

        async def safe_analyze(agent, name: str, ctx_: dict) -> AgentReport:
            try:
                async with self._llm_semaphore:
                    # Small delay between consecutive calls to ease rate limits
                    await asyncio.sleep(2)
                    report = await agent.analyze_async(symbol, ctx_)
                logger.info("  %s [%s] Signal=%s Score=%.1f",
                            tag, name, report.signal, report.score)
                return report
            except Exception as e:
                logger.error("  %s [%s] FAILED: %s", tag, name, e)
                return AgentReport(
                    agent_name=name, agent_role="analyst",
                    symbol=symbol, reasoning=f"Analysis failed: {e}",
                    confidence=0.0,
                )

        # Phase 2: Core analysts in parallel
        reports: list[AgentReport] = list(await asyncio.gather(
            safe_analyze(agents["fundamental"], "fundamental", ctx),
            safe_analyze(agents["technical"], "technical", ctx),
            safe_analyze(agents["sentiment"], "sentiment", ctx),
        ))

        # Phase 3: Bull/Bear debate in parallel
        ctx3 = {"prior_reports": reports, **ctx}
        bull_report, bear_report = await asyncio.gather(
            safe_analyze(agents["bull"], "bull", ctx3),
            safe_analyze(agents["bear"], "bear", ctx3),
        )
        reports.extend([bull_report, bear_report])

        net_conviction = (bull_report.score - bear_report.score) / 10.0
        debate = DebateReport(
            symbol=symbol,
            bull_thesis=bull_report.reasoning,
            bear_thesis=bear_report.reasoning,
            bull_score=bull_report.score,
            bear_score=bear_report.score,
            synthesis=f"Bull={bull_report.score}/10, Bear={bear_report.score}/10",
            net_conviction=net_conviction,
        )

        # Phase 4: Quant + Risk (sequential)
        ctx4 = {"prior_reports": reports, "debate_report": debate.model_dump(), **ctx}
        quant_report = await safe_analyze(agents["quant"], "QuantTrader", ctx4)
        reports.append(quant_report)
        ctx4["prior_reports"] = reports
        risk_report = await safe_analyze(agents["risk"], "RiskManager", ctx4)
        reports.append(risk_report)

        # Phase 5: Fund manager decision
        horizon_fm = _HorizonFundManager(self._base_fund_manager, hcfg)
        async with self._llm_semaphore:
            decision = await asyncio.to_thread(
                horizon_fm.decide, symbol, reports, debate, trade_history, quant_signals
            )
        portfolio_state = self.data.get_portfolio_state()
        decision.portfolio_snapshot = portfolio_state.model_dump()
        decision.trade_history = trade_history

        logger.info("  %s DECISION: %s (confidence=%.2f)",
                     tag, decision.action, decision.confidence)
        return decision

    async def analyze_stock_async(self, symbol: str) -> MultiHorizonDecision:
        """Run all horizon teams for one stock."""
        logger.info("=" * 60)
        logger.info("Multi-Horizon Analysis for %s", symbol)
        logger.info("=" * 60)

        # Phase 1: Data pre-fetch (shared across all horizons)
        logger.info("[Phase 1] Pre-fetching shared data for %s...", symbol)
        await asyncio.to_thread(self.data.get_stock_snapshot, symbol)
        await asyncio.to_thread(self.data.get_financial_data, symbol)
        await asyncio.to_thread(self.data.get_technical_indicators, symbol)
        await asyncio.to_thread(self.data.get_risk_metrics, symbol)
        await asyncio.to_thread(self.data.get_news, symbol)
        await asyncio.to_thread(self.data.get_insider_trades, symbol)

        snapshot = self.data.get_stock_snapshot(symbol)
        quant_data = await asyncio.to_thread(self._build_quant_data, symbol)
        portfolio_state = self.data.get_portfolio_state()
        trade_history = self.data.get_trade_history()
        portfolio_context = {
            "portfolio": portfolio_state.model_dump(),
            "trade_history": trade_history,
        }

        # Run all requested horizons — SEQUENTIALLY to avoid rate limits
        # (3 horizons × 8 LLM calls each = 24 calls; sequential horizons, parallel within)
        logger.info("[Phase 2-5] Running %d horizon teams...", len(self.horizons))
        decisions: dict[Horizon, FinalDecision] = {}
        for horizon in self.horizons:
            try:
                decision = await self._run_single_horizon(
                    symbol, horizon, quant_data, portfolio_context, trade_history
                )
                decisions[horizon] = decision
            except Exception as e:
                logger.error("Horizon %s failed: %s", horizon.value, e)
                decisions[horizon] = FinalDecision(
                    symbol=symbol, name=snapshot.name,
                    current_price=snapshot.current_price,
                    summary=f"{horizon.value} analysis failed: {e}",
                    horizon=horizon.value,
                    horizon_label=get_horizon_config(horizon).label_cn,
                )

        # Build consensus
        consensus = self._compute_consensus(decisions)

        return MultiHorizonDecision(
            symbol=symbol,
            name=snapshot.name,
            current_price=snapshot.current_price,
            short_term=decisions.get(Horizon.SHORT),
            mid_term=decisions.get(Horizon.MID),
            long_term=decisions.get(Horizon.LONG),
            **consensus,
        )

    def _compute_consensus(self, decisions: dict[Horizon, FinalDecision]) -> dict:
        """Derive consensus from the three horizon decisions."""
        actions = [d.action for d in decisions.values() if d.action]
        confidences = [d.confidence for d in decisions.values() if d.confidence > 0]

        buy_count = actions.count("BUY")
        sell_count = actions.count("SELL")
        hold_count = actions.count("HOLD")

        if buy_count >= 2:
            consensus_action = "BUY"
        elif sell_count >= 2:
            consensus_action = "SELL"
        elif buy_count == 1 and hold_count >= 1 and sell_count == 0:
            consensus_action = "HOLD"  # cautious: one BUY isn't enough
        elif sell_count == 1 and hold_count >= 1 and buy_count == 0:
            consensus_action = "HOLD"  # cautious: one SELL isn't enough
        else:
            consensus_action = "HOLD"

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.5

        # Build summary
        parts = []
        for horizon, decision in decisions.items():
            hcfg = get_horizon_config(horizon)
            parts.append(f"{hcfg.label_cn}({hcfg.label}): {decision.action} "
                        f"(置信度{decision.confidence:.0%})")

        agreement = "一致" if len(set(actions)) == 1 else "分歧"
        summary = (
            f"三周期{agreement}：" + "；".join(parts) + "。"
            f"综合建议：{consensus_action}。"
        )

        return {
            "consensus_action": consensus_action,
            "consensus_confidence": round(avg_conf, 2),
            "consensus_summary": summary,
        }

    def analyze_stock(self, symbol: str) -> MultiHorizonDecision:
        """Sync wrapper."""
        return asyncio.run(self.analyze_stock_async(symbol))

    async def analyze_watchlist_async(self) -> list[MultiHorizonDecision]:
        """Analyze all watchlist stocks."""
        results = []
        for symbol in self.settings.watchlist:
            try:
                result = await self.analyze_stock_async(symbol)
                results.append(result)
            except Exception as e:
                logger.error("Failed to analyze %s: %s", symbol, e)
                results.append(MultiHorizonDecision(
                    symbol=symbol,
                    consensus_summary=f"Analysis failed: {e}",
                ))
        return results

    def analyze_watchlist(self) -> list[MultiHorizonDecision]:
        """Sync wrapper."""
        return asyncio.run(self.analyze_watchlist_async())
