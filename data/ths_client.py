"""同花顺 account client based on local export files."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from stock_agents.models.portfolio import PortfolioState, Position

logger = logging.getLogger(__name__)


class THSClient:
    """Read-only client for 同花顺 account exports."""

    def __init__(
        self,
        positions_file: str | None = None,
        cash_file: str | None = None,
        watchlist_file: str | None = None,
        total_capital: float = 0.0,
    ):
        self.positions_file = Path(positions_file).expanduser() if positions_file else None
        self.cash_file = Path(cash_file).expanduser() if cash_file else None
        self.watchlist_file = Path(watchlist_file).expanduser() if watchlist_file else None
        self.total_capital = float(total_capital or 0.0)

    def connect(self) -> bool:
        """Validate configured files. No remote connection is required."""
        if self.positions_file and self.positions_file.exists():
            return True
        if self.cash_file and self.cash_file.exists():
            return True
        if self.watchlist_file and self.watchlist_file.exists():
            return True
        logger.warning(
            "THS files not found. Configure ths.positions_file and/or ths.cash_file and/or ths.watchlist_file."
        )
        return False

    def _read_table(self, path: Path) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        if path.suffix.lower() == ".json":
            try:
                return pd.read_json(path)
            except Exception as e:
                logger.warning("Failed to parse json file %s: %s", path, e)
                return pd.DataFrame()

        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                return pd.read_csv(path, encoding=encoding)
            except Exception:
                continue
        logger.warning("Failed to parse csv file %s", path)
        return pd.DataFrame()

    def _pick(self, row: pd.Series, candidates: list[str], default=0):
        for key in candidates:
            if key in row and pd.notna(row[key]):
                return row[key]
        return default

    def _to_float(self, value, default: float = 0.0) -> float:
        if value is None:
            return default
        text = str(value).strip().replace(",", "")
        if text.endswith("%"):
            return float(text[:-1]) / 100.0
        try:
            return float(text)
        except Exception:
            return default

    def _to_int(self, value, default: int = 0) -> int:
        try:
            return int(float(str(value).strip().replace(",", "")))
        except Exception:
            return default

    def _normalize_symbol(self, symbol: str) -> str:
        code = symbol.strip()
        if "." in code and code.split(".")[-1].isdigit():
            code = code.split(".")[-1]
        if code.endswith(".0"):
            code = code[:-2]
        digits = "".join(ch for ch in code if ch.isdigit())
        if not digits:
            return code
        if len(digits) <= 6:
            return digits.zfill(6)
        return digits[-6:]

    def _extract_symbols_from_table(self, df: pd.DataFrame) -> list[str]:
        if df.empty:
            return []
        symbol_columns = ["证券代码", "股票代码", "代码", "symbol", "code"]
        values: list[str] = []
        for col in symbol_columns:
            if col in df.columns:
                values.extend(df[col].tolist())
        if not values and len(df.columns) >= 1:
            values.extend(df.iloc[:, 0].tolist())

        symbols: list[str] = []
        seen: set[str] = set()
        for raw in values:
            text = str(raw).strip()
            if not text:
                continue
            code = self._normalize_symbol(text)
            if not code.isdigit():
                continue
            if code in seen:
                continue
            seen.add(code)
            symbols.append(code)
        return symbols

    def _load_positions(self) -> list[Position]:
        if not self.positions_file:
            return []
        df = self._read_table(self.positions_file)
        if df.empty:
            return []

        positions: list[Position] = []
        for _, row in df.iterrows():
            symbol = str(self._pick(row, ["证券代码", "股票代码", "代码", "symbol", "code"], "")).strip()
            if not symbol:
                continue
            symbol = self._normalize_symbol(symbol)
            name = str(self._pick(row, ["证券名称", "股票名称", "名称", "name"], "")).strip()
            shares = self._to_int(self._pick(row, ["股票余额", "持仓数量", "数量", "shares", "qty"], 0))
            avg_cost = self._to_float(self._pick(row, ["成本价", "参考成本价", "买入成本", "avg_cost", "cost_price"], 0))
            current_price = self._to_float(self._pick(row, ["最新价", "现价", "市价", "current_price", "last_price"], 0))
            market_value = self._to_float(self._pick(row, ["参考市值", "市值", "market_value", "market_val"], 0))
            pnl = self._to_float(self._pick(row, ["浮动盈亏", "盈亏", "unrealized_pnl", "pl_val"], 0))

            if market_value <= 0 and shares > 0 and current_price > 0:
                market_value = shares * current_price
            if pnl == 0 and shares > 0 and avg_cost > 0 and market_value > 0:
                pnl = market_value - (avg_cost * shares)

            cost_amount = avg_cost * shares
            pnl_pct = pnl / cost_amount if cost_amount > 0 else 0.0
            positions.append(Position(
                symbol=symbol,
                name=name,
                shares=shares,
                avg_cost=avg_cost,
                current_price=current_price,
                market_value=market_value,
                unrealized_pnl=pnl,
                unrealized_pnl_pct=pnl_pct,
                weight_pct=0.0,
            ))
        return positions

    def _load_cash(self) -> float:
        if not self.cash_file:
            return 0.0
        df = self._read_table(self.cash_file)
        if df.empty:
            return 0.0

        if {"key", "value"}.issubset(set(df.columns)):
            mapping = {str(k): v for k, v in zip(df["key"], df["value"], strict=False)}
            for k in ("可用资金", "可取资金", "cash", "available_cash"):
                if k in mapping:
                    return self._to_float(mapping[k], 0.0)

        first = df.iloc[0]
        for key in ("可用资金", "可取资金", "可用余额", "cash", "available_cash"):
            if key in first:
                return self._to_float(first[key], 0.0)

        # key-value style in first 2 columns
        if len(df.columns) >= 2:
            first_col = str(df.columns[0])
            second_col = str(df.columns[1])
            mapping = {str(k): v for k, v in zip(df[first_col], df[second_col], strict=False)}
            for k in ("可用资金", "可取资金", "cash", "available_cash"):
                if k in mapping:
                    return self._to_float(mapping[k], 0.0)
        return 0.0

    def get_portfolio_state(self) -> PortfolioState:
        """Return a normalized portfolio snapshot from local files."""
        positions = self._load_positions()
        market_value = sum(p.market_value for p in positions)
        total_pnl = sum(p.unrealized_pnl for p in positions)
        cash = self._load_cash()
        if cash <= 0 and self.total_capital > 0:
            cash = max(self.total_capital - market_value, 0.0)

        total_value = market_value + cash
        for p in positions:
            p.weight_pct = p.market_value / total_value if total_value > 0 else 0.0

        return PortfolioState(
            total_value=total_value,
            cash=cash,
            positions=positions,
            total_unrealized_pnl=total_pnl,
        )

    def get_watchlist_symbols(self) -> list[str]:
        """Load watchlist symbols from THS exports, with positions fallback."""
        if self.watchlist_file:
            df = self._read_table(self.watchlist_file)
            symbols = self._extract_symbols_from_table(df)
            if symbols:
                return symbols

        if self.positions_file:
            df = self._read_table(self.positions_file)
            symbols = self._extract_symbols_from_table(df)
            if symbols:
                return symbols
        return []

    def disconnect(self) -> None:
        """No-op for local file client."""
        return None
