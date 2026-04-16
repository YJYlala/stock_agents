"""Backtest performance metrics."""

import numpy as np
import pandas as pd


def compute_backtest_metrics(
    returns: pd.Series,
    initial_capital: float,
    final_equity: float,
    trading_days: int,
    risk_free_rate: float = 0.02,
) -> dict:
    """Compute backtest performance metrics."""
    if returns.empty or len(returns) < 5:
        return {}

    returns_clean = returns.dropna()
    daily_rf = risk_free_rate / 245

    # Total return
    total_return = (final_equity - initial_capital) / initial_capital

    # CAGR
    years = trading_days / 245
    cagr = (final_equity / initial_capital) ** (1 / max(years, 0.01)) - 1 if years > 0 else 0

    # Volatility
    vol_annual = float(returns_clean.std() * np.sqrt(245))

    # Sharpe
    excess = returns_clean - daily_rf
    sharpe = float(excess.mean() / (returns_clean.std() + 1e-10) * np.sqrt(245))

    # Max drawdown
    cumulative = (1 + returns_clean).cumprod()
    peak = cumulative.expanding().max()
    drawdown = (cumulative - peak) / peak
    max_dd = float(drawdown.min())

    # Win rate
    winning = (returns_clean > 0).sum()
    total = len(returns_clean)
    win_rate = winning / total if total > 0 else 0

    # Profit factor
    gains = returns_clean[returns_clean > 0].sum()
    losses = abs(returns_clean[returns_clean < 0].sum())
    profit_factor = float(gains / (losses + 1e-10))

    return {
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "volatility_annual_pct": round(vol_annual * 100, 2),
        "win_rate_pct": round(win_rate * 100, 1),
        "profit_factor": round(profit_factor, 2),
        "trading_days": trading_days,
    }
