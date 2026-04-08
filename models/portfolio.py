"""Portfolio and risk models."""

from pydantic import BaseModel, Field


class Position(BaseModel):
    """A single stock position."""
    symbol: str
    name: str = ""
    shares: int = 0
    avg_cost: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    weight_pct: float = 0.0


class PortfolioState(BaseModel):
    """Current portfolio snapshot."""
    total_value: float = 0.0
    cash: float = 0.0
    positions: list[Position] = Field(default_factory=list)
    total_unrealized_pnl: float = 0.0


class RiskMetrics(BaseModel):
    """Portfolio risk metrics."""
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    value_at_risk_95: float = 0.0
    volatility_annual: float = 0.0
    beta: float = 0.0
