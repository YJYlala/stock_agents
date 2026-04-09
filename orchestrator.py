"""Orchestrator - runs the 5-phase agent pipeline."""

import logging

from stock_agents.agents.fundamental_analyst import FundamentalAnalyst
from stock_agents.agents.fund_manager import FundManager
from stock_agents.llm import (
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

        # Build primary provider (github_models or anthropic)
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

    def analyze_stock(self, symbol: str) -> FinalDecision:
        """Run full 5-phase pipeline for one stock."""
        logger.info("=" * 60)
        logger.info("Starting analysis for %s", symbol)
        logger.info("=" * 60)

        # ── Phase 1: Data pre-fetch (handled lazily by data_manager with caching)
        logger.info("[Phase 1] Pre-fetching data for %s...", symbol)
        self.data.get_stock_snapshot(symbol)
        self.data.get_financial_data(symbol)
        self.data.get_technical_indicators(symbol)

        # Build portfolio context once — shared by ALL phases
        portfolio_state = self.data.get_portfolio_state()
        trade_history = self.data.get_trade_history()
        portfolio_context = {
            "portfolio": portfolio_state.model_dump(),
            "trade_history": trade_history,
        }

        # ── Phase 2: Independent analysis (sequential to respect API rate limits)
        logger.info("[Phase 2] Running independent analysis (3 agents)...")
        phase2_reports: list[AgentReport] = []

        for agent, agent_name in [
            (self.fundamental, "fundamental"),
            (self.technical, "technical"),
            (self.sentiment, "sentiment"),
        ]:
            try:
                report = agent.analyze(symbol, portfolio_context)
                phase2_reports.append(report)
                logger.info("  [%s] Signal=%s Score=%.1f Confidence=%.2f",
                            agent_name, report.signal, report.score, report.confidence)
            except Exception as e:
                logger.error("  [%s] FAILED: %s", agent_name, e)
                phase2_reports.append(AgentReport(
                    agent_name=agent_name, agent_role="analyst",
                    symbol=symbol, reasoning=f"Analysis failed: {e}",
                    confidence=0.0,
                ))

        # ── Phase 3: Bull/Bear debate (sequential to avoid rate limits)
        logger.info("[Phase 3] Running bull/bear debate...")
        context_phase3 = {"prior_reports": phase2_reports, **portfolio_context}

        for agent, label in [(self.bull, "bull"), (self.bear, "bear")]:
            try:
                report = agent.analyze(symbol, context_phase3)
            except Exception as e:
                logger.error("  [%s] FAILED: %s", label, e)
                report = AgentReport(
                    agent_name=agent.name, agent_role=agent.role,
                    symbol=symbol, reasoning=f"Analysis failed: {e}",
                    confidence=0.0,
                )
            phase2_reports.append(report)
            if label == "bull":
                bull_report = report
            else:
                bear_report = report

        # Synthesize debate
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

        # ── Phase 4: Risk & Sizing (sequential)
        logger.info("[Phase 4] Running quant trader and risk manager...")
        context_phase4 = {
            "prior_reports": phase2_reports,
            "debate_report": debate.model_dump(),
            **portfolio_context,
        }

        try:
            quant_report = self.quant.analyze(symbol, context_phase4)
        except Exception as e:
            logger.error("  [QuantTrader] FAILED: %s", e)
            quant_report = AgentReport(
                agent_name="QuantTrader", agent_role="量化交易员",
                symbol=symbol, reasoning=f"Analysis failed: {e}",
                confidence=0.0,
            )
        phase2_reports.append(quant_report)
        logger.info("  [QuantTrader] Signal=%s Confidence=%.2f",
                     quant_report.signal, quant_report.confidence)

        context_phase4["prior_reports"] = phase2_reports
        try:
            risk_report = self.risk.analyze(symbol, context_phase4)
        except Exception as e:
            logger.error("  [RiskManager] FAILED: %s", e)
            risk_report = AgentReport(
                agent_name="RiskManager", agent_role="Risk Management",
                symbol=symbol, reasoning=f"Analysis failed: {e}",
                confidence=0.0,
            )
        phase2_reports.append(risk_report)
        logger.info("  [RiskManager] Signal=%s Confidence=%.2f",
                     risk_report.signal, risk_report.confidence)

        # ── Phase 5: Final decision
        logger.info("[Phase 5] Fund manager making final decision...")
        decision = self.fund_manager.decide(symbol, phase2_reports, debate, trade_history)
        decision.portfolio_snapshot = portfolio_state.model_dump()
        decision.trade_history = trade_history
        logger.info("  DECISION: %s (confidence=%.2f)", decision.action, decision.confidence)

        return decision

    def analyze_watchlist(self) -> list[FinalDecision]:
        """Analyze all stocks in the watchlist sequentially."""
        decisions = []
        for symbol in self.settings.watchlist:
            try:
                decision = self.analyze_stock(symbol)
                decisions.append(decision)
            except Exception as e:
                logger.error("Failed to analyze %s: %s", symbol, e)
                decisions.append(FinalDecision(
                    symbol=symbol,
                    summary=f"Analysis failed: {e}",
                ))
        return decisions
