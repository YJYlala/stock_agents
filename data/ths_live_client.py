"""Live 同花顺 client via easytrader — auto-fetches watchlist, positions, cash.

Supports two connection modes:
  1. connect()  — attach to an already-running, already-logged-in 同花顺下单客户端
  2. login()    — auto-launch the client, fill in 国信证券 credentials, and connect

How it works (based on shidenggui/easytrader source code):
  - easytrader.use("ths")  →  ClientTrader, login() is a no-op (abstract)
  - easytrader.use("universal_client")  →  UniversalClientTrader, has real login()
    that launches xiadan.exe, finds the login window, types user/password, clicks login.
  - Both share the same balance/position/buy/sell API (ClientTrader base class).

For auto-login we use "universal_client"; for attach-only we use "ths".

Prerequisites:
  1. Install 同花顺独立下单程序 (xiadan.exe)
     Download from: https://www.10jqka.com.cn/ → 交易 → 独立下单
     Or search "同花顺下单" at https://download.10jqka.com.cn/
  2. Set in .env:
       THS_BROKER_USER=<your 国信证券 资金账号>
       THS_BROKER_PASSWORD=<your 国信证券 登录密码>
  3. Set exe_path in config.yaml to your xiadan.exe path, e.g.:
       ths:
         exe_path: "C:\\同花顺软件\\同花顺\\xiadan.exe"

References:
  - https://github.com/shidenggui/easytrader  (9.5k stars, main project)
  - https://github.com/Fryt1/Frytrader  (captcha handling fork)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path

from stock_agents.models.portfolio import PortfolioState, Position

logger = logging.getLogger(__name__)


class THSLiveClient:
    """Connects to 同花顺下单客户端 via easytrader.

    Uses 'universal_client' mode for auto-login (has real login() impl),
    falls back to 'ths' mode for attach-only.
    """

    def __init__(
        self,
        exe_path: str | None = None,
        broker_user: str | None = None,
        broker_password: str | None = None,
        comm_password: str | None = None,
    ):
        self.exe_path = exe_path
        self.broker_user = broker_user or os.getenv("THS_BROKER_USER", "")
        self.broker_password = broker_password or os.getenv("THS_BROKER_PASSWORD", "")
        self.comm_password = comm_password or os.getenv("THS_COMM_PASSWORD", "")
        self._user = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    def connect(self) -> bool:
        """Attach to an already-running, already-logged-in 同花顺下单客户端.

        Uses easytrader.use("ths").connect(exe_path) which calls
        pywinauto.Application().connect(path=exe_path).
        The client must already be open and logged in.
        """
        try:
            import easytrader  # type: ignore
        except ImportError:
            logger.error(
                "easytrader is not installed. Run: pip install easytrader"
            )
            return False

        try:
            self._user = easytrader.use("ths")
            if self.exe_path:
                self._user.connect(self.exe_path)
            else:
                self._user.connect()
            logger.info("Connected to 同花顺下单客户端 (attach mode)")
            return True
        except Exception as e:
            logger.error("Failed to connect to 同花顺: %s", e)
            return False

    def login(self) -> bool:
        """Auto-launch 同花顺下单客户端 and login with broker credentials.

        Uses easytrader.use("universal_client").prepare(config_path) which:
          1. Starts xiadan.exe if not already running
          2. Finds the login dialog window (class_name='#32770')
          3. Types username into Edit1
          4. Clicks the login button (button7)
          5. Waits for main trading window to appear
          6. Connects to the running process

        Requires:
          - 同花顺独立下单程序 (xiadan.exe) installed
          - THS_BROKER_USER and THS_BROKER_PASSWORD set in .env
          - exe_path set in config.yaml (or auto-detected)
        """
        try:
            import easytrader  # type: ignore
        except ImportError:
            logger.error("easytrader not installed. Run: pip install easytrader")
            return False

        if not self.broker_user or not self.broker_password:
            logger.error(
                "Broker credentials not set. "
                "Set THS_BROKER_USER and THS_BROKER_PASSWORD in .env"
            )
            return False

        if not self.exe_path:
            logger.error(
                "exe_path not set. Set ths.exe_path in config.yaml to "
                "your xiadan.exe path, e.g.: C:\\同花顺软件\\同花顺\\xiadan.exe"
            )
            return False

        try:
            # easytrader's universal_client has a real login() that uses
            # pywinauto to automate the login dialog.
            # prepare() accepts either a config JSON file or keyword args.
            self._user = easytrader.use("universal_client")

            # Build a temp config JSON (easytrader's prepare() reads it)
            config_data = {
                "user": self.broker_user,
                "password": self.broker_password,
                "exe_path": self.exe_path,
            }
            if self.comm_password:
                config_data["comm_password"] = self.comm_password

            config_file = Path(tempfile.gettempdir()) / "ths_login_config.json"
            config_file.write_text(
                json.dumps(config_data, ensure_ascii=False), encoding="utf-8"
            )

            try:
                self._user.prepare(str(config_file))
            finally:
                # Clean up credentials file immediately
                config_file.unlink(missing_ok=True)

            logger.info(
                "同花顺下单客户端 launched and logged in as %s",
                self.broker_user[:3] + "***",
            )
            return True
        except Exception as e:
            logger.error("THS auto-login failed: %s", e)
            logger.info(
                "Tips:\n"
                "  1. Make sure 同花顺独立下单程序 (xiadan.exe) is installed\n"
                "  2. Download from https://www.10jqka.com.cn/ → 交易 → 独立下单\n"
                "     or https://download.10jqka.com.cn/\n"
                "  3. Set ths.exe_path in config.yaml to the xiadan.exe path\n"
                "  4. Check THS_BROKER_USER / THS_BROKER_PASSWORD in .env\n"
                "  5. If captcha is required, try Frytrader fork:\n"
                "     pip install git+https://github.com/Fryt1/Frytrader.git"
            )
            return False

    def disconnect(self) -> None:
        self._user = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_symbol(code: str) -> str:
        code = str(code).strip()
        if "." in code:
            code = code.split(".")[-1]
        if code.endswith(".0"):
            code = code[:-2]
        digits = "".join(ch for ch in code if ch.isdigit())
        if not digits:
            return code
        return digits.zfill(6) if len(digits) <= 6 else digits[-6:]

    @staticmethod
    def _safe_float(val, default: float = 0.0) -> float:
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(val, default: int = 0) -> int:
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return default

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------
    def get_portfolio_state(self) -> PortfolioState:
        """Fetch balance + positions from the live 同花顺 client."""
        if not self._user:
            return PortfolioState()

        # --- Balance ---
        try:
            balance_raw = self._user.balance
            # easytrader returns a list of dicts (one per account)
            bal = balance_raw[0] if isinstance(balance_raw, list) else balance_raw
        except Exception as e:
            logger.warning("Failed to get balance: %s", e)
            bal = {}

        cash = self._safe_float(
            bal.get("可用金额", bal.get("可用资金", bal.get("资金余额", 0)))
        )
        total_value = self._safe_float(
            bal.get("总资产", bal.get("资产总值", 0))
        )

        # --- Positions ---
        positions: list[Position] = []
        total_pnl = 0.0
        try:
            pos_raw = self._user.position
        except Exception as e:
            logger.warning("Failed to get positions: %s", e)
            pos_raw = []

        for row in pos_raw:
            symbol = self._normalize_symbol(
                row.get("证券代码", row.get("股票代码", ""))
            )
            if not symbol:
                continue
            name = str(row.get("证券名称", row.get("股票名称", ""))).strip()
            shares = self._safe_int(row.get("股票余额", row.get("当前持仓", row.get("数量", 0))))
            avg_cost = self._safe_float(row.get("成本价", row.get("参考成本价", 0)))
            current_price = self._safe_float(row.get("最新价", row.get("市价", 0)))
            market_value = self._safe_float(row.get("市值", row.get("参考市值", 0)))
            pnl = self._safe_float(row.get("浮动盈亏", row.get("盈亏", 0)))

            if market_value <= 0 and shares > 0 and current_price > 0:
                market_value = shares * current_price
            cost_amount = avg_cost * shares
            pnl_pct = pnl / cost_amount if cost_amount > 0 else 0.0
            weight = market_value / total_value if total_value > 0 else 0.0

            positions.append(Position(
                symbol=symbol,
                name=name,
                shares=shares,
                avg_cost=avg_cost,
                current_price=current_price,
                market_value=market_value,
                unrealized_pnl=pnl,
                unrealized_pnl_pct=pnl_pct,
                weight_pct=weight,
            ))
            total_pnl += pnl

        return PortfolioState(
            total_value=total_value if total_value > 0 else (cash + sum(p.market_value for p in positions)),
            cash=cash,
            positions=positions,
            total_unrealized_pnl=total_pnl,
        )

    # ------------------------------------------------------------------
    # Watchlist  (positions-based: held stocks are the watchlist)
    # ------------------------------------------------------------------
    def get_watchlist_symbols(self) -> list[str]:
        """Return symbols from current positions as the de-facto watchlist.

        easytrader doesn't expose 同花顺's "自选股" list directly, so we
        treat current holdings as the watchlist.  Users can combine this
        with config.yaml ``watchlist`` entries for extra symbols.
        """
        if not self._user:
            return []
        try:
            pos_raw = self._user.position
        except Exception as e:
            logger.warning("Failed to get position for watchlist: %s", e)
            return []

        seen: set[str] = set()
        symbols: list[str] = []
        for row in pos_raw:
            code = self._normalize_symbol(
                row.get("证券代码", row.get("股票代码", ""))
            )
            if code and code not in seen:
                seen.add(code)
                symbols.append(code)
        return symbols
