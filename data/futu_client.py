"""Futu OpenD client for account data (read-only)."""

import logging

from stock_agents.models.portfolio import PortfolioState, Position

logger = logging.getLogger(__name__)


class FutuClient:
    """Read-only client for Futu OpenD API."""

    def __init__(self, host: str = "127.0.0.1", port: int = 11111):
        self.host = host
        self.port = port
        self._quote_ctx = None
        self._trade_ctx = None

    def connect(self) -> bool:
        """Connect to Futu OpenD."""
        try:
            from futu import OpenQuoteContext, OpenSecTradeContext, TrdEnv, TrdMarket

            self._quote_ctx = OpenQuoteContext(host=self.host, port=self.port)
            self._trade_ctx = OpenSecTradeContext(
                host=self.host, port=self.port,
                filter_trdmarket=TrdMarket.CN,
                trd_env=TrdEnv.REAL,
            )
            logger.info("Connected to Futu OpenD at %s:%d", self.host, self.port)
            return True
        except Exception as e:
            logger.warning("Failed to connect to Futu OpenD: %s", e)
            return False

    def get_portfolio_state(self) -> PortfolioState:
        """Get current portfolio state from Futu."""
        if not self._trade_ctx:
            return PortfolioState()

        try:
            from futu import RET_OK

            # Get account funds
            ret, data = self._trade_ctx.accinfo_query()
            cash = 0.0
            total_value = 0.0
            if ret == RET_OK and not data.empty:
                row = data.iloc[0]
                cash = float(row.get("cash", 0) or 0)
                total_value = float(row.get("total_assets", 0) or 0)

            # Get positions
            ret, data = self._trade_ctx.position_list_query()
            positions = []
            total_pnl = 0.0
            if ret == RET_OK and not data.empty:
                for _, row in data.iterrows():
                    mkt_val = float(row.get("market_val", 0) or 0)
                    pnl = float(row.get("pl_val", 0) or 0)
                    cost = float(row.get("cost_price", 0) or 0)
                    price = float(row.get("last_price", 0) or 0)
                    shares = int(row.get("qty", 0) or 0)

                    weight = mkt_val / total_value if total_value > 0 else 0
                    pnl_pct = pnl / (cost * shares) if cost * shares > 0 else 0

                    # Strip market prefix from code (e.g., "SH.600519" -> "600519")
                    code = str(row.get("code", ""))
                    if "." in code:
                        code = code.split(".")[-1]

                    positions.append(Position(
                        symbol=code,
                        name=str(row.get("stock_name", "")),
                        shares=shares,
                        avg_cost=cost,
                        current_price=price,
                        market_value=mkt_val,
                        unrealized_pnl=pnl,
                        unrealized_pnl_pct=pnl_pct,
                        weight_pct=weight,
                    ))
                    total_pnl += pnl

            return PortfolioState(
                total_value=total_value,
                cash=cash,
                positions=positions,
                total_unrealized_pnl=total_pnl,
            )
        except Exception as e:
            logger.error("Failed to get portfolio from Futu: %s", e)
            return PortfolioState()

    def disconnect(self) -> None:
        """Disconnect from Futu OpenD."""
        if self._quote_ctx:
            self._quote_ctx.close()
        if self._trade_ctx:
            self._trade_ctx.close()
        logger.info("Disconnected from Futu OpenD")
