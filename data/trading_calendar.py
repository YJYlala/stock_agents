"""A-share trading calendar — check if today is a trading day.

Uses AKShare's trade date history to determine whether the market is open.
Falls back to a simple weekday check if AKShare is unavailable.
"""

from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)


def is_trading_day(check_date: date | None = None) -> bool:
    """Return True if check_date (default: today) is an A-share trading day.

    Uses AKShare tool_trade_date_hist_sina() which returns the full history
    of Shanghai Exchange trading dates. Falls back to weekday-only check.
    """
    if check_date is None:
        check_date = date.today()

    # Quick reject: weekends are never trading days
    if check_date.weekday() >= 5:
        logger.info("%s is a weekend — not a trading day", check_date)
        return False

    try:
        import akshare as ak

        df = ak.tool_trade_date_hist_sina()
        # Column is 'trade_date', values are strings like '2024-01-02'
        trade_dates = set(str(d) for d in df["trade_date"].tolist())
        date_str = check_date.strftime("%Y-%m-%d")

        if date_str in trade_dates:
            logger.info("%s is a trading day ✓", check_date)
            return True
        else:
            logger.info("%s is NOT a trading day (holiday)", check_date)
            return False

    except Exception as e:
        logger.warning(
            "Could not fetch trading calendar: %s — falling back to weekday check", e
        )
        # Weekday check already passed above, so assume it's a trading day
        return True


def next_trading_day(after_date: date | None = None) -> date:
    """Return the next trading day after the given date."""
    from datetime import timedelta

    if after_date is None:
        after_date = date.today()

    candidate = after_date + timedelta(days=1)
    # Search up to 15 days ahead (covers long holidays like Spring Festival)
    for _ in range(15):
        if is_trading_day(candidate):
            return candidate
        candidate += timedelta(days=1)

    # Fallback: return next weekday
    candidate = after_date + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate
