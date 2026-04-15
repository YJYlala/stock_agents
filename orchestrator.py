"""Orchestrator - runs the 5-phase agent pipeline."""

import asyncio
import logging

from stock_agents.agents.fundamental_analyst import FundamentalAnalyst
from stock_agents.agents.fund_manager import FundManager
from stock_agents.data.market_context import MarketContext
from stock_agents.data.news_curator import curate_news
from stock_agents.indicators.quant_engine import annotate_null_fields
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


def build_quant_data(data: DataManager, symbol: str) -> dict:
    """Collect raw data needed by the quant engine — shared by both orchestrators."""
    snapshot = data.get_stock_snapshot(symbol)
    financials = data.get_financial_data(symbol)
    indicators = data.get_technical_indicators(symbol)
    risk_metrics = data.get_risk_metrics(symbol)
    portfolio = data.get_portfolio_state()

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
        "portfolio_value": portfolio.total_value or 0,
        "portfolio_positions": positions_data,
        "atr": indicators.atr_14,
    }


def get_agent_llm(
    settings: Settings,
    llm_cache: dict[str, object],
    agent_type: str,
    is_final: bool = False,
):
    """Resolve LLM client for an agent with per-agent model overrides and caching."""
    agent_models = settings.llm.agent_models
    if agent_type in agent_models:
        model = agent_models[agent_type]
    elif is_final:
        model = settings.llm.model_final
    else:
        model = settings.llm.model

    if model not in llm_cache:
        llm_cache[model] = TradingOrchestrator._build_llm(settings, model)
    return llm_cache[model]


class TradingOrchestrator:
    """Runs the full 5-phase multi-agent analysis pipeline."""

    def __init__(self, settings: Settings, account_client=None):
        self.settings = settings
        self.data = DataManager(settings, account_client=account_client)
        self.market_context = MarketContext()

        # LLM clients — build per-agent where config differs, share where same
        self._llm_cache: dict[str, object] = {}
        agent_llm = self._get_agent_llm
        self.llm = self._build_llm(settings, settings.llm.model)
        self.llm_final = self._build_llm(settings, settings.llm.model_final)

        # Initialize agents (each gets its own or shared LLM based on agent_models config)
        self.fundamental = FundamentalAnalyst(agent_llm("fundamental"), self.data)
        self.technical = TechnicalAnalyst(agent_llm("technical"), self.data)
        self.sentiment = SentimentAnalyst(agent_llm("sentiment"), self.data)
        self.bull = BullResearcher(agent_llm("bull"), self.data)
        self.bear = BearResearcher(agent_llm("bear"), self.data)
        self.quant = QuantTrader(agent_llm("quant"), self.data)
        self.risk = RiskManager(agent_llm("risk"), self.data)
        self.fund_manager = FundManager(agent_llm("fund_manager", is_final=True), self.data)

    def _get_agent_llm(self, agent_type: str, is_final: bool = False):
        """Get LLM client for an agent, respecting per-agent model overrides."""
        return get_agent_llm(self.settings, self._llm_cache, agent_type, is_final)

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
            if provider == "github_models":
                # GitHubModelsLLMClient resolves token itself
                # (cached copilot token, env vars, gh CLI)
                primary = GitHubModelsLLMClient(
                    model=model,
                    max_tokens=settings.llm.max_tokens,
                    temperature=settings.llm.temperature,
                )
            elif provider == "azure_openai":
                api_key = settings.llm.api_key
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
                api_key = settings.llm.api_key
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

        quant_data = build_quant_data(self.data, symbol)

        risk_limits = {
            "max_single_position_pct": self.settings.risk.max_single_position_pct,
            "max_sector_pct": self.settings.risk.max_sector_pct,
            "max_drawdown_pct": self.settings.risk.max_drawdown_pct,
        }

        return run_quant_pipeline(
            **quant_data,
            risk_limits=risk_limits,
        )

    async def analyze_stock_async(self, symbol: str) -> FinalDecision:
        """Run full 5-phase pipeline for one stock using async parallel calls."""
        logger.info("=" * 60)
        logger.info("Starting analysis for %s", symbol)
        logger.info("=" * 60)

        # ── Phase 0: Market context (cached — only fetches on first call)
        logger.info("[Phase 0] Fetching market context...")
        market_ctx = await asyncio.to_thread(self.market_context.get_context)
        stock_industry = await asyncio.to_thread(self.market_context.get_stock_industry, symbol)
        market_context_text = await asyncio.to_thread(
            self.market_context.format_for_prompt, symbol
        )
        logger.info("[Phase 0] Market context ready (%d indices, industry=%s)",
                     len(market_ctx.get("market_indices", {})),
                     stock_industry.get("industry_name", "N/A"))

        # ── Phase 1: Data pre-fetch + quant engine — ALL computation before LLM calls
        logger.info("[Phase 1] Pre-fetching data and running quant engine for %s...", symbol)
        await asyncio.to_thread(self.data.get_stock_snapshot, symbol)
        await asyncio.to_thread(self.data.get_financial_data, symbol)
        await asyncio.to_thread(self.data.get_technical_indicators, symbol)
        await asyncio.to_thread(self.data.get_risk_metrics, symbol)
        # Pre-fetch news, insider trades, and company announcements
        await asyncio.to_thread(self.data.get_news, symbol)
        await asyncio.to_thread(self.data.get_insider_trades, symbol)
        await asyncio.to_thread(self.data.get_announcements, symbol)

        # Run quant engine — ALL numerical computation happens HERE in code
        quant_signals = await asyncio.to_thread(self._run_quant_engine, symbol)

        # Annotate null fields so LLMs understand WHY values are missing
        annotate_null_fields(quant_signals)

        logger.info("  [QuantEngine] composite=%.2f signal=%s kelly=%.4f",
                     quant_signals.get("quant_signal", {}).get("composite_score", 0),
                     quant_signals.get("quant_signal", {}).get("signal", "N/A"),
                     quant_signals.get("quant_signal", {}).get("kelly_fraction", 0))

        # ── Phase 0.5: AI news curation (per stock, cheap LLM)
        logger.info("[Phase 0.5] Curating news for %s...", symbol)
        snapshot = self.data.get_stock_snapshot(symbol)
        raw_news = self.data.get_news(symbol)
        announcements = self.data.get_announcements(symbol)
        curated_news = await asyncio.to_thread(
            curate_news,
            self.llm,  # Use the base LLM (cheap model)
            symbol,
            snapshot.name,
            raw_news,
            market_context_text,
            stock_industry.get("industry_name", ""),
            announcements,
        )
        logger.info("[Phase 0.5] News curated: sentiment=%s, %d events, %d risks, %d announcements",
                     curated_news.get("sentiment_summary", "N/A"),
                     len(curated_news.get("company_events", [])),
                     len(curated_news.get("risk_flags", [])),
                     len(announcements))

        portfolio_state = self.data.get_portfolio_state()
        trade_history = self.data.get_trade_history()
        portfolio_context = {
            "portfolio": portfolio_state.model_dump(),
            "trade_history": trade_history,
            "quant_signals": quant_signals,  # pre-computed + annotated for ALL agents
            "market_context": market_context_text,  # macro context for all agents
            "curated_news": curated_news,  # AI-curated news digest
            "announcements": announcements,  # company 公告 (last 90 days)
        }

        # ── Phase 2: Independent analysis — all 3 run in PARALLEL
        logger.info("[Phase 2] Running independent analysis (3 agents in parallel)...")

        async def safe_analyze(agent, name: str, ctx: dict) -> AgentReport | None:
            """Run one agent — returns None on failure (no fake defaults)."""
            try:
                report = await agent.analyze_async(symbol, ctx)
                logger.info("  [%s] Signal=%s Score=%.1f Confidence=%.2f",
                            name, report.signal, report.score, report.confidence)
                return report
            except Exception as e:
                logger.error("  [%s] FAILED: %s", name, e)
                return None

        phase2_results = await asyncio.gather(
            safe_analyze(self.fundamental, "fundamental", portfolio_context),
            safe_analyze(self.technical, "technical", portfolio_context),
            safe_analyze(self.sentiment, "sentiment", portfolio_context),
        )
        phase2_reports: list[AgentReport] = [r for r in phase2_results if r is not None]
        logger.info("[Phase 2] %d/%d agents succeeded", len(phase2_reports), len(phase2_results))
        if not phase2_reports:
            raise RuntimeError(f"All Phase 2 agents failed for {symbol} — cannot produce a decision")

        # ── Phase 3: Bull/Bear debate — both run in PARALLEL
        logger.info("[Phase 3] Running bull/bear debate (parallel)...")
        context_phase3 = {"prior_reports": phase2_reports, **portfolio_context}

        bull_result, bear_result = await asyncio.gather(
            safe_analyze(self.bull, "bull", context_phase3),
            safe_analyze(self.bear, "bear", context_phase3),
        )

        debate: DebateReport | None = None
        if bull_result and bear_result:
            phase2_reports.extend([bull_result, bear_result])
            net_conviction = (bull_result.score - bear_result.score) / 10.0
            debate = DebateReport(
                symbol=symbol,
                bull_thesis=bull_result.reasoning,
                bear_thesis=bear_result.reasoning,
                bull_score=bull_result.score,
                bear_score=bear_result.score,
                synthesis=f"Bull score: {bull_result.score}/10, Bear score: {bear_result.score}/10",
                net_conviction=net_conviction,
            )
            logger.info("  Bull=%.1f Bear=%.1f Net=%.2f",
                        debate.bull_score, debate.bear_score, debate.net_conviction)
        else:
            failed = [("bull" if not bull_result else None), ("bear" if not bear_result else None)]
            logger.warning("[Phase 3] Debate incomplete — failed: %s", [f for f in failed if f])
            if bull_result:
                phase2_reports.append(bull_result)
            if bear_result:
                phase2_reports.append(bear_result)

        # ── Phase 4: Quant trader then risk manager (risk needs quant output)
        logger.info("[Phase 4] Running quant trader and risk manager...")
        context_phase4 = {
            "prior_reports": phase2_reports,
            "debate_report": debate.model_dump() if debate else {},
            **portfolio_context,
        }

        quant_report = await safe_analyze(self.quant, "QuantTrader", context_phase4)
        if quant_report:
            phase2_reports.append(quant_report)
            logger.info("  [QuantTrader] Signal=%s Confidence=%.2f",
                        quant_report.signal, quant_report.confidence)
        else:
            logger.warning("  [QuantTrader] FAILED — proceeding without quant report")

        context_phase4["prior_reports"] = phase2_reports
        risk_report = await safe_analyze(self.risk, "RiskManager", context_phase4)
        if risk_report:
            phase2_reports.append(risk_report)
            logger.info("  [RiskManager] Signal=%s Confidence=%.2f",
                        risk_report.signal, risk_report.confidence)
        else:
            logger.warning("  [RiskManager] FAILED — proceeding without risk report")

        # ── Phase 5: Final decision
        logger.info("[Phase 5] Fund manager making final decision...")
        decision = await asyncio.to_thread(
            self.fund_manager.decide, symbol, phase2_reports, debate, trade_history, quant_signals,
            market_context_text, curated_news,
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
                # Skip this symbol — do not append a fake default decision
        return decisions

    def analyze_watchlist(self) -> list[FinalDecision]:
        """Sync wrapper around analyze_watchlist_async."""
        return asyncio.run(self.analyze_watchlist_async())

