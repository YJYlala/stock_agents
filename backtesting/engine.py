"""Backtesting engine for strategy evaluation."""

import logging
from datetime import datetime

import numpy as np
import pandas as pd

from stock_agents.backtesting.metrics import compute_backtest_metrics
from stock_agents.data.akshare_client import AKShareClient

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Simple backtesting engine using technical indicator signals."""

    def __init__(self, initial_capital: float = 1_000_000):
        self.initial_capital = initial_capital
        self.akshare = AKShareClient()

    def run(
        self,
        symbol: str,
        start_date: str = "2024-01-01",
        end_date: str = "2025-12-31",
        ma_fast: int = 5,
        ma_slow: int = 20,
    ) -> dict:
        """Run a simple MA crossover backtest.

        This is a fast, cost-free backtest (no LLM calls).
        For full agent-based backtests, use the orchestrator per-day (expensive).
        """
        logger.info("Running backtest for %s from %s to %s", symbol, start_date, end_date)

        # Get data
        df = self.akshare.get_stock_history(symbol, days=500)
        if df.empty:
            return {"error": "No data available"}

        df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()
        if len(df) < ma_slow + 5:
            return {"error": "Insufficient data for backtest"}

        # Compute signals
        df["ma_fast"] = df["close"].rolling(window=ma_fast).mean()
        df["ma_slow"] = df["close"].rolling(window=ma_slow).mean()
        df = df.dropna().reset_index(drop=True)

        # Simulate trades
        capital = self.initial_capital
        shares = 0
        trades = []
        equity_curve = []

        for i in range(1, len(df)):
            price = df["close"].iloc[i]
            ma_f = df["ma_fast"].iloc[i]
            ma_s = df["ma_slow"].iloc[i]
            ma_f_prev = df["ma_fast"].iloc[i - 1]
            ma_s_prev = df["ma_slow"].iloc[i - 1]

            # Golden cross (buy)
            if ma_f_prev <= ma_s_prev and ma_f > ma_s and shares == 0:
                shares = int(capital * 0.95 / price) // 100 * 100
                if shares > 0:
                    cost = shares * price
                    capital -= cost
                    trades.append({
                        "date": str(df["date"].iloc[i]),
                        "action": "BUY",
                        "price": price,
                        "shares": shares,
                    })

            # Dead cross (sell)
            elif ma_f_prev >= ma_s_prev and ma_f < ma_s and shares > 0:
                revenue = shares * price
                capital += revenue
                trades.append({
                    "date": str(df["date"].iloc[i]),
                    "action": "SELL",
                    "price": price,
                    "shares": shares,
                })
                shares = 0

            total = capital + shares * price
            equity_curve.append({
                "date": str(df["date"].iloc[i]),
                "equity": total,
                "price": price,
            })

        # Final equity
        final_equity = capital + shares * df["close"].iloc[-1]
        equity_series = pd.Series([e["equity"] for e in equity_curve])
        returns = equity_series.pct_change().dropna()

        # Buy & hold comparison
        buy_hold_return = (df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0]

        metrics = compute_backtest_metrics(returns, self.initial_capital, final_equity, len(df))

        return {
            "symbol": symbol,
            "period": f"{start_date} to {end_date}",
            "strategy": f"MA({ma_fast}/{ma_slow}) Crossover",
            "initial_capital": self.initial_capital,
            "final_equity": round(final_equity, 2),
            "total_return": round((final_equity - self.initial_capital) / self.initial_capital * 100, 2),
            "buy_hold_return": round(buy_hold_return * 100, 2),
            "trade_count": len(trades),
            "trades": trades[-10:],  # Last 10 trades
            "metrics": metrics,
        }
