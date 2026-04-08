"""Portfolio and stock risk metrics computation."""

import numpy as np
import pandas as pd


def compute_risk_metrics(
    returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
    risk_free_rate: float = 0.02,
    trading_days: int = 245,
) -> dict:
    """Compute risk metrics from a return series."""
    if returns.empty or len(returns) < 10:
        return {"sharpe_ratio": 0, "sortino_ratio": 0, "max_drawdown": 0,
                "volatility_annual": 0, "beta": 0, "value_at_risk_95": 0}

    returns_clean = returns.dropna()
    daily_rf = risk_free_rate / trading_days

    # Annualized volatility
    vol_annual = float(returns_clean.std() * np.sqrt(trading_days))

    # Sharpe ratio
    excess = returns_clean - daily_rf
    sharpe = float(excess.mean() / (returns_clean.std() + 1e-10) * np.sqrt(trading_days))

    # Sortino ratio (downside deviation)
    downside = returns_clean[returns_clean < 0]
    downside_std = float(downside.std()) if len(downside) > 1 else 1e-10
    sortino = float(excess.mean() / (downside_std + 1e-10) * np.sqrt(trading_days))

    # Max drawdown
    cumulative = (1 + returns_clean).cumprod()
    peak = cumulative.expanding().max()
    drawdown = (cumulative - peak) / peak
    max_dd = float(drawdown.min())

    # Current drawdown
    current_dd = float(drawdown.iloc[-1]) if len(drawdown) > 0 else 0.0

    # VaR 95%
    var_95 = float(np.percentile(returns_clean, 5))

    # Beta (vs benchmark)
    beta = 0.0
    if benchmark_returns is not None and len(benchmark_returns) >= 10:
        aligned = pd.DataFrame({"stock": returns_clean, "bench": benchmark_returns}).dropna()
        if len(aligned) > 10:
            cov = np.cov(aligned["stock"], aligned["bench"])
            beta = float(cov[0, 1] / (cov[1, 1] + 1e-10))

    return {
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "max_drawdown": round(max_dd, 4),
        "current_drawdown": round(current_dd, 4),
        "volatility_annual": round(vol_annual, 4),
        "value_at_risk_95": round(var_95, 4),
        "beta": round(beta, 3),
    }
