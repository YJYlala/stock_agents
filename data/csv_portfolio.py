"""CSV-based portfolio tracker — no broker connection needed.

Reads portfolio.csv (a simple trade log) to compute current holdings, cash, and PnL.
Users manually record their trades; the system reads this to understand their situation.

CSV format:
  date,action,symbol,name,shares,price,commission,note
  2026-04-08,init_cash,,,,,55351.10,初始资金
  2026-04-08,buy,603993,洛阳钼业,1100,17.956,5.00,建仓
  2026-04-09,sell,603993,洛阳钼业,500,19.50,5.00,部分止盈
"""

import csv
import logging
from datetime import datetime
from pathlib import Path

from stock_agents.models.portfolio import PortfolioState, Position

logger = logging.getLogger(__name__)

DEFAULT_CSV = Path(__file__).parent.parent / "portfolio.csv"


def load_portfolio(
    csv_path: str | Path = DEFAULT_CSV,
    price_lookup: dict[str, float] | None = None,
) -> PortfolioState:
    """Build PortfolioState from portfolio.csv trade log.

    Args:
        csv_path: Path to portfolio.csv
        price_lookup: {symbol: current_price} for live PnL. If missing, uses avg_cost.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        logger.warning("Portfolio CSV not found: %s — returning empty portfolio", csv_path)
        return PortfolioState()

    cash = 0.0
    holdings: dict[str, dict] = {}  # {symbol: {name, shares, total_cost}}

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            action = (row.get("action") or "").strip().lower()
            symbol = (row.get("symbol") or "").strip()
            name = (row.get("name") or "").strip()
            shares = int(float(row.get("shares") or 0))
            price = float(row.get("price") or 0)
            commission = float(row.get("commission") or 0)
            note = (row.get("note") or "").strip()

            if action == "init_cash":
                # Cash amount can be in 'note' or 'commission' column
                for field in [note, str(commission)]:
                    try:
                        val = float(field)
                        if val > 0:
                            cash += val
                            break
                    except (ValueError, TypeError):
                        continue
            elif action == "buy" and symbol:
                cost = shares * price + commission
                cash -= cost
                h = holdings.setdefault(symbol, {"name": name, "shares": 0, "total_cost": 0.0})
                h["shares"] += shares
                h["total_cost"] += shares * price  # track pure stock cost (excl commission)
                if name:
                    h["name"] = name
            elif action == "sell" and symbol:
                proceeds = shares * price - commission
                cash += proceeds
                if symbol in holdings:
                    h = holdings[symbol]
                    if h["shares"] > 0:
                        cost_per_share = h["total_cost"] / h["shares"]
                        h["total_cost"] -= cost_per_share * shares
                    h["shares"] -= shares
                    if h["shares"] <= 0:
                        del holdings[symbol]

    # Build positions with live prices
    positions = []
    total_market_value = 0.0
    total_unrealized_pnl = 0.0
    prices = price_lookup or {}

    for sym, h in holdings.items():
        if h["shares"] <= 0:
            continue
        avg_cost = h["total_cost"] / h["shares"] if h["shares"] > 0 else 0
        current_price = prices.get(sym, avg_cost)
        market_value = h["shares"] * current_price
        unrealized_pnl = market_value - h["total_cost"]
        pnl_pct = (unrealized_pnl / h["total_cost"] * 100) if h["total_cost"] > 0 else 0

        total_market_value += market_value
        total_unrealized_pnl += unrealized_pnl

        positions.append(Position(
            symbol=sym,
            name=h["name"],
            shares=h["shares"],
            avg_cost=round(avg_cost, 3),
            current_price=round(current_price, 3),
            market_value=round(market_value, 2),
            unrealized_pnl=round(unrealized_pnl, 2),
            unrealized_pnl_pct=round(pnl_pct, 2),
        ))

    total_value = cash + total_market_value
    for pos in positions:
        pos.weight_pct = round(pos.market_value / total_value * 100, 2) if total_value > 0 else 0

    return PortfolioState(
        total_value=round(total_value, 2),
        cash=round(cash, 2),
        positions=positions,
        total_unrealized_pnl=round(total_unrealized_pnl, 2),
    )


def record_trade(
    csv_path: str | Path,
    action: str,
    symbol: str = "",
    name: str = "",
    shares: int = 0,
    price: float = 0.0,
    commission: float = 0.0,
    note: str = "",
):
    """Append a trade row to portfolio.csv."""
    csv_path = Path(csv_path)
    exists = csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["date", "action", "symbol", "name", "shares", "price", "commission", "note"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d"),
            action, symbol, name, shares, price, commission, note,
        ])


def get_trade_history(csv_path: str | Path = DEFAULT_CSV) -> list[dict]:
    """Return raw trade records from portfolio.csv."""
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return []
    trades = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            action = (row.get("action") or "").strip().lower()
            if action in ("buy", "sell"):
                trades.append({
                    "date": (row.get("date") or "").strip(),
                    "action": action,
                    "symbol": (row.get("symbol") or "").strip(),
                    "name": (row.get("name") or "").strip(),
                    "shares": int(float(row.get("shares") or 0)),
                    "price": float(row.get("price") or 0),
                    "commission": float(row.get("commission") or 0),
                    "note": (row.get("note") or "").strip(),
                })
    return trades


def get_held_symbols(csv_path: str | Path = DEFAULT_CSV) -> list[str]:
    """Return list of currently held stock symbols."""
    state = load_portfolio(csv_path)
    return [p.symbol for p in state.positions if p.shares > 0]
