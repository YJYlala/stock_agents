"""Tests for CSV portfolio and trade history."""

import csv
import tempfile
from pathlib import Path

import pytest

from stock_agents.data.csv_portfolio import load_portfolio, get_trade_history


@pytest.fixture
def sample_csv(tmp_path):
    """Create a sample portfolio CSV for testing."""
    csv_path = tmp_path / "portfolio.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "action", "symbol", "name", "shares", "price", "commission", "note"])
        writer.writerow(["2026-04-01", "init_cash", "", "", "", "", "100000", "初始资金"])
        writer.writerow(["2026-04-02", "buy", "600519", "贵州茅台", "100", "1800.50", "5.00", "建仓"])
        writer.writerow(["2026-04-03", "buy", "000858", "五粮液", "200", "150.00", "5.00", "建仓"])
        writer.writerow(["2026-04-05", "sell", "000858", "五粮液", "100", "155.00", "5.00", "部分止盈"])
    return csv_path


class TestLoadPortfolio:
    def test_initial_cash(self, sample_csv):
        state = load_portfolio(sample_csv)
        # Initial 100000 - buy 600519 (100*1800.50+5) - buy 000858 (200*150+5) + sell (100*155-5)
        expected_cash = 100000 - 180055 - 30005 + 15495
        assert abs(state.cash - expected_cash) < 0.01, f"Cash={state.cash}, expected={expected_cash}"

    def test_positions(self, sample_csv):
        state = load_portfolio(sample_csv)
        assert len(state.positions) == 2
        symbols = {p.symbol for p in state.positions}
        assert "600519" in symbols
        assert "000858" in symbols

    def test_position_shares(self, sample_csv):
        state = load_portfolio(sample_csv)
        for pos in state.positions:
            if pos.symbol == "600519":
                assert pos.shares == 100
            elif pos.symbol == "000858":
                assert pos.shares == 100  # 200 bought, 100 sold

    def test_total_value(self, sample_csv):
        state = load_portfolio(sample_csv)
        assert state.total_value > 0

    def test_empty_file(self, tmp_path):
        csv_path = tmp_path / "empty.csv"
        csv_path.write_text("date,action,symbol,name,shares,price,commission,note\n")
        state = load_portfolio(csv_path)
        assert state.cash == 0
        assert len(state.positions) == 0


class TestTradeHistory:
    def test_get_trades(self, sample_csv):
        trades = get_trade_history(sample_csv)
        assert len(trades) == 3  # 1 buy + 1 buy + 1 sell (init_cash excluded)

    def test_trade_fields(self, sample_csv):
        trades = get_trade_history(sample_csv)
        t = trades[0]
        assert t["action"] == "buy"
        assert t["symbol"] == "600519"
        assert t["shares"] == 100
        assert t["price"] == 1800.50

    def test_no_file(self, tmp_path):
        trades = get_trade_history(tmp_path / "nonexistent.csv")
        assert trades == []

    def test_sell_trade(self, sample_csv):
        trades = get_trade_history(sample_csv)
        sell_trades = [t for t in trades if t["action"] == "sell"]
        assert len(sell_trades) == 1
        assert sell_trades[0]["symbol"] == "000858"
        assert sell_trades[0]["shares"] == 100


class TestRealPortfolio:
    """Test with actual portfolio.csv (skip if not present)."""

    @pytest.fixture
    def real_csv(self):
        path = Path(__file__).resolve().parent.parent / "portfolio.csv"
        if not path.exists():
            pytest.skip("portfolio.csv not found")
        return path

    def test_load_real_portfolio(self, real_csv):
        state = load_portfolio(real_csv)
        print(f"\nReal portfolio: cash={state.cash:.2f}, "
              f"positions={len(state.positions)}, "
              f"total_value={state.total_value:.2f}")
        assert state.total_value > 0

    def test_real_trade_history(self, real_csv):
        trades = get_trade_history(real_csv)
        print(f"\nTrade history: {len(trades)} trades")
        for t in trades:
            print(f"  {t['date']} {t['action'].upper()} {t['shares']}x{t['symbol']} @ {t['price']}")
        assert isinstance(trades, list)
