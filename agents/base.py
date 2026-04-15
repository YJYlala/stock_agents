"""Base agent class for all analyst agents."""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime

from stock_agents.data.data_manager import DataManager
from stock_agents.llm import LLMClient
from stock_agents.models.signals import AgentReport

logger = logging.getLogger(__name__)


class AgentAnalysisError(ValueError):
    """Raised when the LLM fails to return a valid structured AgentReport."""


class BaseAgent(ABC):
    """Abstract base class for all agents."""

    name: str = "BaseAgent"
    role: str = "Agent"

    def __init__(self, llm: LLMClient, data: DataManager):
        self.llm = llm
        self.data = data

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the agent's system prompt."""

    @abstractmethod
    def gather_data(self, symbol: str, context: dict | None = None) -> dict:
        """Collect all data this agent needs."""

    def analyze(self, symbol: str, context: dict | None = None) -> AgentReport:
        """Run full analysis: gather data -> LLM -> parse report.

        Raises AgentAnalysisError if the LLM returns an unparseable or empty result.
        Never returns a default/fallback report — callers must handle the exception.
        """
        logger.info("[%s] Analyzing %s...", self.name, symbol)

        # Gather data
        data = self.gather_data(symbol, context)

        # Format user message
        user_msg = (
            f"Analyze stock: {symbol}\n\nData:\n"
            f"{json.dumps(data, ensure_ascii=False, default=str, indent=2)}"
        )

        if context:
            prior_reports = context.get("prior_reports", [])
            if prior_reports:
                user_msg += "\n\nPrior agent reports:\n"
                for report in prior_reports:
                    if isinstance(report, AgentReport):
                        user_msg += f"\n--- {report.agent_name} ({report.agent_role}) ---\n"
                        user_msg += f"Signal: {report.signal} | Score: {report.score}/10 | Confidence: {report.confidence}\n"
                        user_msg += f"Reasoning: {report.reasoning}\n"
                        user_msg += f"Key factors: {', '.join(report.key_factors)}\n"
                        user_msg += f"Risks: {', '.join(report.risks)}\n"
                    elif isinstance(report, dict):
                        user_msg += json.dumps(report, ensure_ascii=False, default=str, indent=2)

            debate = context.get("debate_report")
            if debate:
                user_msg += f"\n\nDebate Report:\n{json.dumps(debate, ensure_ascii=False, default=str, indent=2)}"

            portfolio = context.get("portfolio")
            if portfolio:
                user_msg += f"\n\nPortfolio State:\n{json.dumps(portfolio, ensure_ascii=False, default=str, indent=2)}"

            trade_history = context.get("trade_history")
            if trade_history:
                user_msg += f"\n\nTrade History:\n{json.dumps(trade_history, ensure_ascii=False, default=str, indent=2)}"

        # Call LLM — propagate any LLM-level errors (rate limit, network, etc.)
        result = self.llm.analyze(
            system_prompt=self.get_system_prompt(),
            user_message=user_msg,
            output_schema=AgentReport,
        )

        # Parse structured result
        if isinstance(result, dict) and result:
            logger.debug("[%s] LLM returned dict with keys: %s", self.name, list(result.keys()))
            result.setdefault("agent_name", self.name)
            result.setdefault("agent_role", self.role)
            result.setdefault("symbol", symbol)
            result.setdefault("timestamp", datetime.now().isoformat())
            result["data_used"] = data
            try:
                report = AgentReport(**result)
                # Require at least a real reasoning string — not blank
                if not report.reasoning.strip():
                    raise AgentAnalysisError(
                        f"[{self.name}] LLM returned empty 'reasoning' for {symbol}"
                    )
                return report
            except AgentAnalysisError:
                raise
            except Exception as e:
                raise AgentAnalysisError(
                    f"[{self.name}] Failed to construct AgentReport for {symbol}: {e} | raw={result}"
                ) from e

        raise AgentAnalysisError(
            f"[{self.name}] LLM returned no usable result for {symbol} "
            f"(type={type(result).__name__}, value={str(result)[:200]})"
        )

    async def analyze_async(self, symbol: str, context: dict | None = None) -> AgentReport:
        """Async wrapper — runs analyze() in a thread pool so LLM I/O doesn't block."""
        return await asyncio.to_thread(self.analyze, symbol, context)
