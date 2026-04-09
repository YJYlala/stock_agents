"""Tests for technical indicators and risk metrics computation."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_ohlcv():
    """Generate sample OHLCV data for testing."""
    np.random.seed(42)
    n = 100
    prices = 20 + np.cumsum(np.random.randn(n) * 0.5)
    prices = np.maximum(prices, 5)  # Floor at 5
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n, freq="B"),
        "open": prices + np.random.randn(n) * 0.1,
        "high": prices + abs(np.random.randn(n)) * 0.5,
        "low": prices - abs(np.random.randn(n)) * 0.5,
        "close": prices,
        "volume": np.random.randint(1_000_000, 10_000_000, n),
    })


class TestKDJ:
    def test_kdj_values(self, sample_ohlcv):
        from stock_agents.indicators.technical import compute_kdj
        k, d, j = compute_kdj(sample_ohlcv)
        assert 0 <= k <= 100, f"K should be 0-100, got {k}"
        assert 0 <= d <= 100, f"D should be 0-100, got {d}"
        # J can exceed 0-100 range (by design: J = 3K - 2D)
        print(f"\nKDJ: K={k:.2f} D={d:.2f} J={j:.2f}")

    def test_kdj_minimum_data(self):
        from stock_agents.indicators.technical import compute_kdj
        df = pd.DataFrame({
            "high": [10, 11, 12], "low": [9, 10, 11], "close": [10, 11, 12]
        })
        k, d, j = compute_kdj(df, period=3)
        assert not np.isnan(k)


class TestTechnicalIndicators:
    def test_compute_all(self, sample_ohlcv):
        from stock_agents.indicators.technical import compute_all_indicators
        indicators = compute_all_indicators(sample_ohlcv, symbol="TEST")
        assert indicators.rsi_14 is not None
        assert 0 <= indicators.rsi_14 <= 100
        assert indicators.macd_hist is not None
        assert indicators.ma_5 is not None
        assert indicators.ma_20 is not None
        assert indicators.atr_14 > 0
        print(f"\nIndicators: RSI={indicators.rsi_14:.2f}, MACD_hist={indicators.macd_hist:.4f}, "
              f"MA5={indicators.ma_5:.2f}, ATR={indicators.atr_14:.2f}")

    def test_bollinger_bands(self, sample_ohlcv):
        from stock_agents.indicators.technical import compute_all_indicators
        indicators = compute_all_indicators(sample_ohlcv, symbol="TEST")
        assert indicators.bollinger_upper > indicators.bollinger_lower
        assert indicators.bollinger_upper > indicators.ma_20
        assert indicators.bollinger_lower < indicators.ma_20

    def test_trend_detection(self, sample_ohlcv):
        from stock_agents.indicators.technical import compute_all_indicators
        indicators = compute_all_indicators(sample_ohlcv, symbol="TEST")
        assert indicators.trend in ("bullish", "bearish", "neutral")


class TestRiskMetrics:
    def test_compute_risk_metrics(self, sample_ohlcv):
        from stock_agents.indicators.risk_metrics import compute_risk_metrics
        returns = sample_ohlcv["close"].pct_change().dropna()
        metrics = compute_risk_metrics(returns)
        assert metrics["sharpe_ratio"] is not None
        assert metrics["max_drawdown"] <= 0
        assert metrics["volatility_annual"] > 0
        print(f"\nRisk: Sharpe={metrics['sharpe_ratio']:.2f}, MaxDD={metrics['max_drawdown']:.2%}, "
              f"Vol={metrics['volatility_annual']:.2%}")

    def test_var_95(self, sample_ohlcv):
        from stock_agents.indicators.risk_metrics import compute_risk_metrics
        returns = sample_ohlcv["close"].pct_change().dropna()
        metrics = compute_risk_metrics(returns)
        assert metrics["value_at_risk_95"] < 0, "VaR-95 should be negative (loss)"

    def test_sortino_ratio(self, sample_ohlcv):
        from stock_agents.indicators.risk_metrics import compute_risk_metrics
        returns = sample_ohlcv["close"].pct_change().dropna()
        metrics = compute_risk_metrics(returns)
        assert metrics["sortino_ratio"] is not None
