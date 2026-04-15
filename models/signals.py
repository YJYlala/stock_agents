"""Signal and decision models for agent communication.

Convention: None = data unavailable or not computed.
Scores use None when the agent did not produce a score.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentReport(BaseModel):
    """Standard report produced by every agent."""
    agent_name: str
    agent_role: str
    symbol: str
    timestamp: datetime = Field(default_factory=datetime.now)
    score: float | None = None        # 0-10 scale, None = not scored
    signal: str = "HOLD"              # BUY / SELL / HOLD
    confidence: float | None = None   # 0.0 to 1.0
    reasoning: str = ""
    key_factors: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    data_used: dict[str, Any] = Field(default_factory=dict)


class DebateReport(BaseModel):
    """Output of the bull/bear research debate."""
    symbol: str
    bull_thesis: str = ""
    bear_thesis: str = ""
    bull_score: float | None = None    # None = debate did not produce a score
    bear_score: float | None = None
    synthesis: str = ""
    net_conviction: float | None = None  # -1.0 (bear) to +1.0 (bull)


class FinalDecision(BaseModel):
    """Final output from Fund Manager agent."""
    symbol: str
    name: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)
    action: str = "HOLD"               # BUY / SELL / HOLD
    confidence: float | None = None    # 0.0 to 1.0
    current_price: float | None = None
    target_price: float | None = None
    stop_loss: float | None = None
    position_size_pct: float | None = None
    position_size_shares: int | None = None

    # Multi-dimension scores — None = not provided by LLM
    fundamental_score: float | None = None
    technical_score: float | None = None
    sentiment_score: float | None = None

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

    # Horizon info (optional — set when using multi-horizon analysis)
    horizon: str = ""            # "short", "mid", "long" or "" for default
    horizon_label: str = ""      # "短线", "中线", "长线"
    llm_model: str = ""          # e.g. "gpt-54 (Azure OpenAI)"


class MultiHorizonDecision(BaseModel):
    """Combined decision from all three horizon teams."""
    symbol: str
    name: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)
    current_price: float | None = None

    short_term: FinalDecision | None = None
    mid_term: FinalDecision | None = None
    long_term: FinalDecision | None = None

    consensus_action: str = "HOLD"
    consensus_confidence: float | None = None
    consensus_summary: str = ""
