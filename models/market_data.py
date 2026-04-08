"""Market data models."""

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
    amount: float = 0.0  # turnover in CNY


class StockSnapshot(BaseModel):
    """Current state of a stock with history."""
    symbol: str
    name: str = ""
    exchange: str = ""  # "SH" or "SZ"
    current_price: float = 0.0
    change_pct: float = 0.0
    market_cap: float = 0.0
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    history: list[OHLCVBar] = Field(default_factory=list)


class FinancialData(BaseModel):
    """Financial statement data for analysis."""
    symbol: str
    revenue: list[float] = Field(default_factory=list)
    net_profit: list[float] = Field(default_factory=list)
    total_assets: float = 0.0
    total_liabilities: float = 0.0
    total_equity: float = 0.0
    operating_cash_flow: list[float] = Field(default_factory=list)
    eps: float = 0.0
    roe: float = 0.0
    debt_to_equity: float = 0.0
    gross_margin: float = 0.0
    net_margin: float = 0.0
    revenue_growth: float = 0.0
    profit_growth: float = 0.0
    report_dates: list[str] = Field(default_factory=list)


class TechnicalIndicators(BaseModel):
    """Computed technical indicators."""
    symbol: str
    ma_5: float = 0.0
    ma_10: float = 0.0
    ma_20: float = 0.0
    ma_60: float = 0.0
    ma_120: float = 0.0
    ema_12: float = 0.0
    ema_26: float = 0.0
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    rsi_14: float = 0.0
    bollinger_upper: float = 0.0
    bollinger_middle: float = 0.0
    bollinger_lower: float = 0.0
    kdj_k: float = 0.0
    kdj_d: float = 0.0
    kdj_j: float = 0.0
    atr_14: float = 0.0
    vwap: float = 0.0
    volume_ma_20: float = 0.0
    trend: str = "neutral"  # "bullish" | "bearish" | "neutral"
    support_levels: list[float] = Field(default_factory=list)
    resistance_levels: list[float] = Field(default_factory=list)
