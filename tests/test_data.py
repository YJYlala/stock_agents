"""Tests for stock data acquisition and trading hours detection."""

import pytest
from datetime import datetime, time


def is_trading_time(dt: datetime | None = None) -> dict:
    """Check if given time is during A-share trading hours.

    A-shares trade:
      Morning:   09:30 - 11:30 (CST)
      Afternoon: 13:00 - 15:00 (CST)
      Pre-open:  09:15 - 09:25 (call auction)

    Returns dict with is_trading, session info, and next open/close times.
    """
    if dt is None:
        from zoneinfo import ZoneInfo
        dt = datetime.now(ZoneInfo("Asia/Shanghai"))

    t = dt.time()
    weekday = dt.weekday()  # 0=Mon, 6=Sun

    if weekday >= 5:
        return {"is_trading": False, "session": "weekend", "detail": f"{'Saturday' if weekday == 5 else 'Sunday'}"}

    morning_open = time(9, 30)
    morning_close = time(11, 30)
    afternoon_open = time(13, 0)
    afternoon_close = time(15, 0)
    pre_open_start = time(9, 15)

    if morning_open <= t <= morning_close:
        return {"is_trading": True, "session": "morning", "detail": "09:30-11:30"}
    elif afternoon_open <= t <= afternoon_close:
        return {"is_trading": True, "session": "afternoon", "detail": "13:00-15:00"}
    elif pre_open_start <= t < morning_open:
        return {"is_trading": False, "session": "pre_open_auction", "detail": "09:15-09:30 call auction"}
    elif morning_close < t < afternoon_open:
        return {"is_trading": False, "session": "lunch_break", "detail": "11:30-13:00 lunch"}
    elif t > afternoon_close:
        return {"is_trading": False, "session": "after_hours", "detail": "after 15:00"}
    else:
        return {"is_trading": False, "session": "pre_market", "detail": "before 09:15"}


class TestTradingHours:
    """Test trading hours detection."""

    def test_monday_morning_session(self):
        dt = datetime(2026, 4, 6, 10, 0)  # Monday 10:00
        result = is_trading_time(dt)
        assert result["is_trading"] is True
        assert result["session"] == "morning"

    def test_monday_afternoon_session(self):
        dt = datetime(2026, 4, 6, 14, 0)  # Monday 14:00
        result = is_trading_time(dt)
        assert result["is_trading"] is True
        assert result["session"] == "afternoon"

    def test_lunch_break(self):
        dt = datetime(2026, 4, 6, 12, 0)  # Monday 12:00
        result = is_trading_time(dt)
        assert result["is_trading"] is False
        assert result["session"] == "lunch_break"

    def test_weekend(self):
        dt = datetime(2026, 4, 11, 10, 0)  # Saturday 10:00
        result = is_trading_time(dt)
        assert result["is_trading"] is False
        assert result["session"] == "weekend"

    def test_pre_open_auction(self):
        dt = datetime(2026, 4, 6, 9, 20)  # Monday 09:20
        result = is_trading_time(dt)
        assert result["is_trading"] is False
        assert result["session"] == "pre_open_auction"

    def test_after_hours(self):
        dt = datetime(2026, 4, 6, 16, 0)  # Monday 16:00
        result = is_trading_time(dt)
        assert result["is_trading"] is False
        assert result["session"] == "after_hours"

    def test_current_time(self):
        """Report current trading status (always passes)."""
        result = is_trading_time()
        print(f"\nCurrent trading status: {result}")
        assert "is_trading" in result


class TestAKShareClient:
    """Test AKShare data fetching (requires network)."""

    @pytest.fixture
    def client(self):
        from stock_agents.data.akshare_client import AKShareClient
        return AKShareClient()

    def test_get_stock_history(self, client):
        """Fetch historical data for 603993."""
        df = client.get_stock_history("603993", days=10)
        assert not df.empty, "Should return historical data"
        assert "close" in df.columns
        assert "volume" in df.columns
        assert len(df) > 0
        print(f"\nHistory: {len(df)} bars, last close={df['close'].iloc[-1]}")

    def test_get_realtime_quote(self, client):
        """Fetch real-time quote for 603993."""
        quote = client.get_realtime_quote("603993")
        assert quote["symbol"] == "603993"
        assert quote["current_price"] > 0, "Price should be positive"
        print(f"\nRealtime: {quote['name']} @ {quote['current_price']}")

    def test_get_financial_data(self, client):
        """Fetch financial data for 603993."""
        fin = client.get_financial_metrics("603993")
        assert isinstance(fin, dict)
        print(f"\nFinancials keys: {list(fin.keys())}")

    def test_get_news(self, client):
        """Fetch news for 603993."""
        news = client.get_news("603993")
        assert isinstance(news, list)
        print(f"\nNews: {len(news)} articles")

    def test_symbol_normalization(self, client):
        """Test symbol format normalization."""
        assert client._normalize_symbol("SH.600519") == "600519"
        assert client._normalize_symbol("SZ.000858") == "000858"
        assert client._normalize_symbol("603993") == "603993"
        assert client._to_163_symbol("600519") == "sh600519"
        assert client._to_163_symbol("000858") == "sz000858"

    def test_data_freshness(self, client):
        """Check if the latest data point is from a recent trading day."""
        df = client.get_stock_history("603993", days=5)
        if not df.empty:
            last_date = df["date"].iloc[-1]
            days_old = (datetime.now() - last_date).days
            print(f"\nLast data point: {last_date} ({days_old} days ago)")
            assert days_old < 7, f"Data is {days_old} days old — may be stale"
