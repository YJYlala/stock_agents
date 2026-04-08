"""Technical indicators computation."""

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import MACD, EMAIndicator, SMAIndicator
from ta.volatility import AverageTrueRange, BollingerBands

from stock_agents.models.market_data import TechnicalIndicators


def compute_kdj(df: pd.DataFrame, period: int = 9) -> tuple[float, float, float]:
    """Compute KDJ indicator (popular in A-shares)."""
    low_min = df["low"].rolling(window=period).min()
    high_max = df["high"].rolling(window=period).max()
    rsv = (df["close"] - low_min) / (high_max - low_min + 1e-10) * 100
    rsv = rsv.fillna(50)  # Default RSV to 50 when rolling window insufficient

    k = pd.Series(np.zeros(len(df)), index=df.index, dtype=float)
    d = pd.Series(np.zeros(len(df)), index=df.index, dtype=float)
    k.iloc[0] = 50.0
    d.iloc[0] = 50.0
    for i in range(1, len(df)):
        k.iloc[i] = 2 / 3 * k.iloc[i - 1] + 1 / 3 * rsv.iloc[i]
        d.iloc[i] = 2 / 3 * d.iloc[i - 1] + 1 / 3 * k.iloc[i]
    j = 3 * k - 2 * d
    return float(k.iloc[-1]), float(d.iloc[-1]), float(j.iloc[-1])


def compute_support_resistance(df: pd.DataFrame, window: int = 20) -> tuple[list[float], list[float]]:
    """Compute support and resistance levels from recent pivot points."""
    recent = df.tail(window)
    price = float(df["close"].iloc[-1])

    highs = recent["high"].nlargest(3).tolist()
    lows = recent["low"].nsmallest(3).tolist()

    supports = sorted([l for l in lows if l < price], reverse=True)[:3]
    resistances = sorted([h for h in highs if h > price])[:3]
    return supports, resistances


def compute_all_indicators(df: pd.DataFrame, symbol: str) -> TechnicalIndicators:
    """Compute all technical indicators from OHLCV DataFrame."""
    if df.empty or len(df) < 30:
        return TechnicalIndicators(symbol=symbol)

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"].astype(float)

    # Moving averages
    ma_5 = SMAIndicator(close, window=5).sma_indicator().iloc[-1]
    ma_10 = SMAIndicator(close, window=10).sma_indicator().iloc[-1]
    ma_20 = SMAIndicator(close, window=20).sma_indicator().iloc[-1]
    ma_60 = SMAIndicator(close, window=min(60, len(df))).sma_indicator().iloc[-1] if len(df) >= 60 else ma_20
    ma_120 = SMAIndicator(close, window=min(120, len(df))).sma_indicator().iloc[-1] if len(df) >= 120 else ma_60
    ema_12 = EMAIndicator(close, window=12).ema_indicator().iloc[-1]
    ema_26 = EMAIndicator(close, window=26).ema_indicator().iloc[-1]

    # MACD
    macd_ind = MACD(close, window_slow=26, window_fast=12, window_sign=9)
    macd_val = macd_ind.macd().iloc[-1]
    macd_signal = macd_ind.macd_signal().iloc[-1]
    macd_hist = macd_ind.macd_diff().iloc[-1]

    # RSI
    rsi_14 = RSIIndicator(close, window=14).rsi().iloc[-1]

    # Bollinger Bands
    bb = BollingerBands(close, window=20, window_dev=2)
    bb_upper = bb.bollinger_hband().iloc[-1]
    bb_middle = bb.bollinger_mavg().iloc[-1]
    bb_lower = bb.bollinger_lband().iloc[-1]

    # KDJ
    kdj_k, kdj_d, kdj_j = compute_kdj(df)

    # ATR
    atr_14 = AverageTrueRange(high, low, close, window=14).average_true_range().iloc[-1]

    # VWAP (daily approximation)
    typical_price = (high + low + close) / 3
    vwap = float((typical_price * volume).sum() / (volume.sum() + 1e-10))

    # Volume MA
    vol_ma_20 = float(volume.rolling(window=20).mean().iloc[-1]) if len(df) >= 20 else float(volume.mean())

    # Trend classification
    current = float(close.iloc[-1])
    if current > ma_5 > ma_20 > ma_60:
        trend = "bullish"
    elif current < ma_5 < ma_20 < ma_60:
        trend = "bearish"
    else:
        trend = "neutral"

    # Support/Resistance
    supports, resistances = compute_support_resistance(df)

    # Handle NaN
    def safe(v: float) -> float:
        return 0.0 if (v != v) else float(v)  # NaN check

    return TechnicalIndicators(
        symbol=symbol,
        ma_5=safe(ma_5), ma_10=safe(ma_10), ma_20=safe(ma_20),
        ma_60=safe(ma_60), ma_120=safe(ma_120),
        ema_12=safe(ema_12), ema_26=safe(ema_26),
        macd=safe(macd_val), macd_signal=safe(macd_signal), macd_hist=safe(macd_hist),
        rsi_14=safe(rsi_14),
        bollinger_upper=safe(bb_upper), bollinger_middle=safe(bb_middle), bollinger_lower=safe(bb_lower),
        kdj_k=safe(kdj_k), kdj_d=safe(kdj_d), kdj_j=safe(kdj_j),
        atr_14=safe(atr_14), vwap=safe(vwap), volume_ma_20=safe(vol_ma_20),
        trend=trend,
        support_levels=supports, resistance_levels=resistances,
    )
