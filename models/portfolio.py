"""Portfolio and risk models.

Convention: None = data unavailable. Never use 0.0 to hide missing data.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Position(BaseModel):
    """A single stock position."""
    symbol: str
    name: str = ""
    shares: int = 0
    avg_cost: float | None = None
    current_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    weight_pct: float = 0.0  # computed, 0.0 means no weight


class PortfolioState(BaseModel):
    """Current portfolio snapshot."""
    total_value: float | None = None
    cash: float | None = None
    positions: list[Position] = Field(default_factory=list)
    total_unrealized_pnl: float | None = None


class RiskMetrics(BaseModel):
    """Portfolio risk metrics."""
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown: float | None = None
    current_drawdown: float | None = None
    value_at_risk_95: float | None = None
    volatility_annual: float | None = None
    beta: float | None = None
