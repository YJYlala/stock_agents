"""Market data models.

Convention: metrics that may be unavailable use Optional[float] = None.
None means "data not available" — never use 0.0 as a stand-in for missing.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class OHLCVBar(BaseModel):
    """Single OHLCV bar."""
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float | None = None  # turnover in CNY


class StockSnapshot(BaseModel):
    """Current state of a stock with history."""
    symbol: str
    name: str = ""
    exchange: str = ""  # "SH" or "SZ"
    current_price: float | None = None
    change_pct: float | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    history: list[OHLCVBar] = Field(default_factory=list)


class FinancialData(BaseModel):
    """Financial statement data for analysis."""
    symbol: str
    revenue: list[float] = Field(default_factory=list)
    net_profit: list[float] = Field(default_factory=list)
    total_assets: float | None = None
    total_liabilities: float | None = None
    total_equity: float | None = None
    operating_cash_flow: list[float] = Field(default_factory=list)
    eps: float | None = None
    roe: float | None = None
    debt_to_equity: float | None = None
    gross_margin: float | None = None
    net_margin: float | None = None
    revenue_growth: float | None = None
    profit_growth: float | None = None
    report_dates: list[str] = Field(default_factory=list)


class TechnicalIndicators(BaseModel):
    """Computed technical indicators."""
    symbol: str
    ma_5: float | None = None
    ma_10: float | None = None
    ma_20: float | None = None
    ma_60: float | None = None
    ma_120: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    rsi_14: float | None = None
    bollinger_upper: float | None = None
    bollinger_middle: float | None = None
    bollinger_lower: float | None = None
    kdj_k: float | None = None
    kdj_d: float | None = None
    kdj_j: float | None = None
    atr_14: float | None = None
    vwap: float | None = None
    volume_ma_20: float | None = None
    trend: str = "neutral"  # "bullish" | "bearish" | "neutral"
    support_levels: list[float] = Field(default_factory=list)
    resistance_levels: list[float] = Field(default_factory=list)
