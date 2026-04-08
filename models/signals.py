"""Signal and decision models for agent communication."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentReport(BaseModel):
    """Standard report produced by every agent."""
    agent_name: str
    agent_role: str
    symbol: str
    timestamp: datetime = Field(default_factory=datetime.now)
    score: float = 5.0           # 0-10 scale
    signal: str = "HOLD"         # BUY / SELL / HOLD
    confidence: float = 0.5      # 0.0 to 1.0
    reasoning: str = ""
    key_factors: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    data_used: dict[str, Any] = Field(default_factory=dict)


class DebateReport(BaseModel):
    """Output of the bull/bear research debate."""
    symbol: str
    bull_thesis: str = ""
    bear_thesis: str = ""
    bull_score: float = 5.0
    bear_score: float = 5.0
    synthesis: str = ""
    net_conviction: float = 0.0  # -1.0 (bear) to +1.0 (bull)


class FinalDecision(BaseModel):
    """Final output from Fund Manager agent."""
    symbol: str
    name: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)
    action: str = "HOLD"         # BUY / SELL / HOLD
    confidence: float = 0.5      # 0.0 to 1.0
    current_price: float = 0.0
    target_price: float | None = None
    stop_loss: float | None = None
    position_size_pct: float = 0.0
    position_size_shares: int = 0

    # Multi-dimension scores
    fundamental_score: float = 5.0
    technical_score: float = 5.0
    sentiment_score: float = 5.0

    # Supporting analysis
    summary: str = ""
    decision_methodology: str = ""  # Step-by-step scoring calculation
    bull_case: str = ""
    bear_case: str = ""
    risk_assessment: str = ""

    # All agent reports
    agent_reports: list[AgentReport] = Field(default_factory=list)
    debate_report: DebateReport | None = None

    # Portfolio context for report
    portfolio_snapshot: dict[str, Any] = Field(default_factory=dict)
    trade_history: list[dict[str, Any]] = Field(default_factory=list)
