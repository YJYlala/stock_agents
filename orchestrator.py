"""Orchestrator - runs the 5-phase agent pipeline."""

import asyncio
import logging

from stock_agents.agents.fundamental_analyst import FundamentalAnalyst
from stock_agents.agents.fund_manager import FundManager
from stock_agents.llm import (
    AzureOpenAILLMClient,
    ClaudeLLMClient,
    GitHubModelsLLMClient,
    OllamaLLMClient,
    OpenRouterLLMClient,
    FallbackLLMClient,
)
from stock_agents.agents.quant_trader import QuantTrader
from stock_agents.agents.research_bear import BearResearcher
from stock_agents.agents.research_bull import BullResearcher
from stock_agents.agents.risk_manager import RiskManager
from stock_agents.agents.sentiment_analyst import SentimentAnalyst
from stock_agents.agents.technical_analyst import TechnicalAnalyst
from stock_agents.config.settings import Settings
from stock_agents.data.data_manager import DataManager
from stock_agents.models.signals import AgentReport, DebateReport, FinalDecision

logger = logging.getLogger(__name__)


class TradingOrchestrator:
    """Runs the full 5-phase multi-agent analysis pipeline."""

    def __init__(self, settings: Settings, account_client=None):
        self.settings = settings
        self.data = DataManager(settings, account_client=account_client)

        # LLM clients — choose backend based on config
        self.llm = self._build_llm(settings, settings.llm.model)
        self.llm_final = self._build_llm(settings, settings.llm.model_final)

        # Initialize agents
        self.fundamental = FundamentalAnalyst(self.llm, self.data)
        self.technical = TechnicalAnalyst(self.llm, self.data)
        self.sentiment = SentimentAnalyst(self.llm, self.data)
        self.bull = BullResearcher(self.llm, self.data)
        self.bear = BearResearcher(self.llm, self.data)
        self.quant = QuantTrader(self.llm, self.data)
        self.risk = RiskManager(self.llm, self.data)
        self.fund_manager = FundManager(self.llm_final, self.data)

    @staticmethod
    def _build_llm(settings: Settings, model: str):
        """Create LLM client based on provider config, with automatic fallback."""
        provider = settings.llm.provider

        if provider == "ollama":
            return OllamaLLMClient(
                model=settings.ollama.model,
                max_tokens=settings.ollama.max_tokens,
                temperature=settings.ollama.temperature,
                endpoint=settings.ollama.endpoint,
            )

        if provider == "openrouter":
            primary = OpenRouterLLMClient(
                api_key=settings.openrouter.api_key,
                model=model or settings.openrouter.model,
                max_tokens=settings.openrouter.max_tokens,
                temperature=settings.openrouter.temperature,
                endpoint=settings.openrouter.endpoint,
            )
            if settings.llm.fallback == "ollama":
                fallback = OllamaLLMClient(
                    model=settings.ollama.model,
                    max_tokens=settings.ollama.max_tokens,
                    temperature=settings.ollama.temperature,
                    endpoint=settings.ollama.endpoint,
                )
                return FallbackLLMClient(primary, fallback)
            return primary

        # Build primary provider (github_models, azure_openai, or anthropic)
        try:
            api_key = settings.llm.api_key
            if provider == "github_models":
                primary = GitHubModelsLLMClient(
                    github_token=api_key,
                    model=model,
                    max_tokens=settings.llm.max_tokens,
                    temperature=settings.llm.temperature,
                    endpoint=settings.llm.endpoint,
                )
            elif provider == "azure_openai":
                deployment = settings.llm.azure_deployment or model
                primary = AzureOpenAILLMClient(
                    api_key=api_key,
                    endpoint=settings.llm.endpoint,
                    api_version=settings.llm.azure_api_version,
                    deployment=deployment,
                    max_tokens=settings.llm.max_tokens,
                    temperature=settings.llm.temperature,
                )
            else:  # anthropic
                primary = ClaudeLLMClient(
                    api_key=api_key,
                    model=model,
                    max_tokens=settings.llm.max_tokens,
                    temperature=settings.llm.temperature,
                )
        except Exception as e:
            logger.warning("Primary LLM provider (%s) init failed: %s", provider, e)
            if settings.llm.fallback == "ollama":
                logger.info("Falling back to Ollama (%s)...", settings.ollama.model)
                return OllamaLLMClient(
                    model=settings.ollama.model,
                    max_tokens=settings.ollama.max_tokens,
                    temperature=settings.ollama.temperature,
                    endpoint=settings.ollama.endpoint,
                )
            raise

        # Wrap with runtime fallback if configured
        if settings.llm.fallback == "ollama":
            fallback = OllamaLLMClient(
                model=settings.ollama.model,
                max_tokens=settings.ollama.max_tokens,
                temperature=settings.ollama.temperature,
                endpoint=settings.ollama.endpoint,
            )
            return FallbackLLMClient(primary, fallback)

        return primary

    def _run_quant_engine(self, symbol: str) -> dict:
        """Run the quantitative engine — ALL math computation for this stock."""
        from stock_agents.indicators.quant_engine import run_quant_pipeline

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

        positions_data = []
        for pos in portfolio.positions:
            positions_data.append({
                "symbol": pos.symbol, "weight_pct": pos.weight_pct,
            })

        risk_limits = {
            "max_single_position_pct": self.settings.risk.max_single_position_pct,
            "max_sector_pct": self.settings.risk.max_sector_pct,
            "max_drawdown_pct": self.settings.risk.max_drawdown_pct,
        }

        return run_quant_pipeline(
            indicators=ind_dict,
            financials=fin_dict,
            risk_metrics=risk_metrics,
            current_price=snapshot.current_price,
            market_cap=snapshot.market_cap,
            portfolio_value=portfolio.total_value,
            portfolio_positions=positions_data,
            risk_limits=risk_limits,
            atr=indicators.atr_14,
        )

    async def analyze_stock_async(self, symbol: str) -> FinalDecision:
        """Run full 5-phase pipeline for one stock using async parallel calls."""
        logger.info("=" * 60)
        logger.info("Starting analysis for %s", symbol)
        logger.info("=" * 60)

        # ── Phase 1: Data pre-fetch + quant engine — ALL computation before LLM calls
        logger.info("[Phase 1] Pre-fetching data and running quant engine for %s...", symbol)
        await asyncio.to_thread(self.data.get_stock_snapshot, symbol)
        await asyncio.to_thread(self.data.get_financial_data, symbol)
        await asyncio.to_thread(self.data.get_technical_indicators, symbol)
        await asyncio.to_thread(self.data.get_risk_metrics, symbol)
        # Pre-fetch news and insider trades so sentiment agent doesn't block
        await asyncio.to_thread(self.data.get_news, symbol)
        await asyncio.to_thread(self.data.get_insider_trades, symbol)

        # Run quant engine — ALL numerical computation happens HERE in code
        quant_signals = await asyncio.to_thread(self._run_quant_engine, symbol)
        logger.info("  [QuantEngine] composite=%.2f signal=%s kelly=%.4f",
                     quant_signals.get("quant_signal", {}).get("composite_score", 0),
                     quant_signals.get("quant_signal", {}).get("signal", "N/A"),
                     quant_signals.get("quant_signal", {}).get("kelly_fraction", 0))

        portfolio_state = self.data.get_portfolio_state()
        trade_history = self.data.get_trade_history()
        portfolio_context = {
            "portfolio": portfolio_state.model_dump(),
            "trade_history": trade_history,
            "quant_signals": quant_signals,  # pre-computed for ALL agents
        }

        # ── Phase 2: Independent analysis — all 3 run in PARALLEL
        logger.info("[Phase 2] Running independent analysis (3 agents in parallel)...")

        async def safe_analyze(agent, name: str, ctx: dict) -> AgentReport:
            try:
                report = await agent.analyze_async(symbol, ctx)
                logger.info("  [%s] Signal=%s Score=%.1f Confidence=%.2f",
                            name, report.signal, report.score, report.confidence)
                return report
            except Exception as e:
                logger.error("  [%s] FAILED: %s", name, e)
                return AgentReport(
                    agent_name=name, agent_role="analyst",
                    symbol=symbol, reasoning=f"Analysis failed: {e}",
                    confidence=0.0,
                )

        phase2_reports: list[AgentReport] = list(await asyncio.gather(
            safe_analyze(self.fundamental, "fundamental", portfolio_context),
            safe_analyze(self.technical, "technical", portfolio_context),
            safe_analyze(self.sentiment, "sentiment", portfolio_context),
        ))

        # ── Phase 3: Bull/Bear debate — both run in PARALLEL
        logger.info("[Phase 3] Running bull/bear debate (parallel)...")
        context_phase3 = {"prior_reports": phase2_reports, **portfolio_context}

        bull_report, bear_report = await asyncio.gather(
            safe_analyze(self.bull, "bull", context_phase3),
            safe_analyze(self.bear, "bear", context_phase3),
        )
        phase2_reports.extend([bull_report, bear_report])

        net_conviction = (bull_report.score - bear_report.score) / 10.0
        debate = DebateReport(
            symbol=symbol,
            bull_thesis=bull_report.reasoning,
            bear_thesis=bear_report.reasoning,
            bull_score=bull_report.score,
            bear_score=bear_report.score,
            synthesis=f"Bull score: {bull_report.score}/10, Bear score: {bear_report.score}/10",
            net_conviction=net_conviction,
        )
        logger.info("  Bull=%.1f Bear=%.1f Net=%.2f",
                    debate.bull_score, debate.bear_score, debate.net_conviction)

        # ── Phase 4: Quant trader then risk manager (risk needs quant output)
        logger.info("[Phase 4] Running quant trader and risk manager...")
        context_phase4 = {
            "prior_reports": phase2_reports,
            "debate_report": debate.model_dump(),
            **portfolio_context,
        }

        quant_report = await safe_analyze(self.quant, "QuantTrader", context_phase4)
        phase2_reports.append(quant_report)
        logger.info("  [QuantTrader] Signal=%s Confidence=%.2f",
                    quant_report.signal, quant_report.confidence)

        context_phase4["prior_reports"] = phase2_reports
        risk_report = await safe_analyze(self.risk, "RiskManager", context_phase4)
        phase2_reports.append(risk_report)
        logger.info("  [RiskManager] Signal=%s Confidence=%.2f",
                    risk_report.signal, risk_report.confidence)

        # ── Phase 5: Final decision
        logger.info("[Phase 5] Fund manager making final decision...")
        decision = await asyncio.to_thread(
            self.fund_manager.decide, symbol, phase2_reports, debate, trade_history, quant_signals
        )
        decision.portfolio_snapshot = portfolio_state.model_dump()
        decision.trade_history = trade_history
        logger.info("  DECISION: %s (confidence=%.2f)", decision.action, decision.confidence)

        return decision

    def analyze_stock(self, symbol: str) -> FinalDecision:
        """Sync wrapper around analyze_stock_async for backward compatibility."""
        return asyncio.run(self.analyze_stock_async(symbol))

    async def analyze_watchlist_async(self) -> list[FinalDecision]:
        """Analyze all stocks — each stock runs its phases in parallel internally."""
        decisions = []
        for symbol in self.settings.watchlist:
            try:
                decision = await self.analyze_stock_async(symbol)
                decisions.append(decision)
            except Exception as e:
                logger.error("Failed to analyze %s: %s", symbol, e)
                decisions.append(FinalDecision(
                    symbol=symbol,
                    summary=f"Analysis failed: {e}",
                ))
        return decisions

    def analyze_watchlist(self) -> list[FinalDecision]:
        """Sync wrapper around analyze_watchlist_async."""
        return asyncio.run(self.analyze_watchlist_async())

