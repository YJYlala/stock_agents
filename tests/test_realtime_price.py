"""
Realtime price polling test.

Polls get_realtime_quote() 10 times with 10-second intervals and prints:
  - Current time
  - Current price (sell_1 / best ask — the price shown on trading platforms)
  - Best bid / best ask spread
  - Change %

Usage:
    cd /Users/poly_genai/GenAI
    python -m stock_agents.tests.test_realtime_price
    python -m stock_agents.tests.test_realtime_price 601012
    python -m stock_agents.tests.test_realtime_price 600711 601012 603993
"""

import sys
import time
from datetime import datetime

# allow running from project root
sys.path.insert(0, ".")

from stock_agents.data.akshare_client import AKShareClient  # noqa: E402

POLL_COUNT = 10
POLL_INTERVAL = 10  # seconds


def poll_symbols(symbols: list[str]):
    client = AKShareClient()

    print(f"\n{'=' * 70}")
    print(f"实时价格轮询测试  |  标的: {', '.join(symbols)}")
    print(f"轮询次数: {POLL_COUNT}  |  间隔: {POLL_INTERVAL}s")
    print(f"{'=' * 70}")

    for i in range(1, POLL_COUNT + 1):
        now = datetime.now()
        print(f"\n[第 {i:>2}/{POLL_COUNT} 次]  {now.strftime('%Y-%m-%d  %H:%M:%S')}")
        print(f"  {'代码':<8}  {'名称':<10}  {'现价':>8}  {'买一':>8}  {'卖一':>8}  {'涨跌幅':>8}")
        print(f"  {'-' * 62}")

        for symbol in symbols:
            try:
                q = client.get_realtime_quote(symbol)
                if not q:
                    print(f"  {symbol:<8}  {'N/A':<10}  {'--':>8}  {'--':>8}  {'--':>8}  {'--':>8}")
                    continue

                price = q.get("current_price", 0)
                bid = q.get("best_bid", 0)
                ask = q.get("best_ask", 0)
                chg = q.get("change_pct", 0)
                name = q.get("name", "")[:8]

                chg_str = f"{chg:+.2f}%"
                color_open = "\033[32m" if chg >= 0 else "\033[31m"
                color_close = "\033[0m"

                print(
                    f"  {symbol:<8}  {name:<10}  "
                    f"{color_open}{price:>8.3f}{color_close}  "
                    f"{bid:>8.3f}  {ask:>8.3f}  "
                    f"{color_open}{chg_str:>8}{color_close}"
                )
            except Exception as e:
                print(f"  {symbol:<8}  ERROR: {e}")

        if i < POLL_COUNT:
            print(f"\n  等待 {POLL_INTERVAL}s ...")
            time.sleep(POLL_INTERVAL)

    print(f"\n{'=' * 70}")
    print("轮询完成")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["600711", "601012", "603993"]
    poll_symbols(targets)
