"""Unified data manager combining all data sources."""

import logging

from stock_agents.config.settings import Settings
from stock_agents.data.akshare_client import AKShareClient
from stock_agents.data.cache import DataCache
from stock_agents.data.csv_portfolio import load_portfolio, get_trade_history
from stock_agents.indicators.technical import compute_all_indicators
from stock_agents.indicators.risk_metrics import compute_risk_metrics
from stock_agents.models.market_data import (
    FinancialData, OHLCVBar, StockSnapshot, TechnicalIndicators,
)
from stock_agents.models.portfolio import PortfolioState

logger = logging.getLogger(__name__)


class DataManager:
    """Unified data interface for all agents."""

    def __init__(self, settings: Settings, account_client=None):
        self.settings = settings
        self.akshare = AKShareClient()
        self.account_client = account_client
        self.cache = DataCache(
            cache_dir=settings.cache_dir,
            ttl_seconds=settings.cache.ttl_seconds,
            enabled=settings.cache.enabled,
        )

    def get_stock_snapshot(self, symbol: str) -> StockSnapshot:
        """Get current stock data with history."""
        cache_key = f"snapshot_{symbol}"
        cached = self.cache.get(cache_key)
        if cached:
            return StockSnapshot(**cached)

        # Real-time quote
        quote = self.akshare.get_realtime_quote(symbol)

        # Historical data
        hist_df = self.akshare.get_stock_history(symbol, self.settings.analysis.lookback_days)
        history = []
        if not hist_df.empty:
            for _, row in hist_df.iterrows():
                history.append(OHLCVBar(
                    date=row["date"], open=row["open"], high=row["high"],
                    low=row["low"], close=row["close"],
                    volume=int(row["volume"]), amount=float(row["amount"]),
                ))

        snapshot = StockSnapshot(
            symbol=symbol,
            name=quote.get("name", ""),
            exchange="SH" if symbol.startswith("6") else "SZ",
            current_price=quote.get("current_price", history[-1].close if history else 0),
            change_pct=quote.get("change_pct", 0),
            market_cap=quote.get("market_cap", 0),
            pe_ratio=quote.get("pe_ratio"),
            pb_ratio=quote.get("pb_ratio"),
            history=history,
        )
        self.cache.set(cache_key, snapshot.model_dump())
        return snapshot

    def get_financial_data(self, symbol: str) -> FinancialData:
        """Get financial statement data."""
        cache_key = f"financial_{symbol}"
        cached = self.cache.get(cache_key)
        if cached:
            return FinancialData(**cached)

        metrics = self.akshare.get_financial_metrics(symbol)

        # Try to get income statement for revenue/profit trends
        income_df = self.akshare.get_income_statement(symbol)
        revenue_list = []
        profit_list = []
        report_dates = []
        if not income_df.empty:
            for _, row in income_df.head(self.settings.analysis.financial_quarters).iterrows():
                rev = row.get("营业收入", row.get("一、营业总收入", 0))
                profit = row.get("净利润", row.get("五、净利润", 0))
                revenue_list.append(float(rev or 0))
                profit_list.append(float(profit or 0))
                date_val = row.get("报告日", row.get("报告期", ""))
                report_dates.append(str(date_val))

        # Balance sheet
        bs_df = self.akshare.get_balance_sheet(symbol)
        total_assets = 0.0
        total_liabilities = 0.0
        total_equity = 0.0
        if not bs_df.empty:
            latest = bs_df.iloc[0]
            total_assets = float(latest.get("资产总计", 0) or 0)
            total_liabilities = float(latest.get("负债合计", 0) or 0)
            total_equity = float(latest.get("所有者权益(或股东权益)合计", total_assets - total_liabilities) or 0)

        # Cash flow
        cf_df = self.akshare.get_cash_flow(symbol)
        ocf_list = []
        if not cf_df.empty:
            for _, row in cf_df.head(self.settings.analysis.financial_quarters).iterrows():
                ocf = row.get("经营活动产生的现金流量净额", 0)
                ocf_list.append(float(ocf or 0))

        # Growth rates
        rev_growth = 0.0
        if len(revenue_list) >= 2 and revenue_list[1] != 0:
            rev_growth = (revenue_list[0] - revenue_list[1]) / abs(revenue_list[1]) * 100
        profit_growth = 0.0
        if len(profit_list) >= 2 and profit_list[1] != 0:
            profit_growth = (profit_list[0] - profit_list[1]) / abs(profit_list[1]) * 100

        d_e = metrics.get("debt_to_equity", 0)

        data = FinancialData(
            symbol=symbol,
            revenue=revenue_list,
            net_profit=profit_list,
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            total_equity=total_equity,
            operating_cash_flow=ocf_list,
            eps=metrics.get("eps", 0),
            roe=metrics.get("roe", 0),
            debt_to_equity=d_e,
            gross_margin=metrics.get("gross_margin", 0),
            net_margin=metrics.get("net_margin", 0),
            revenue_growth=rev_growth,
            profit_growth=profit_growth,
            report_dates=report_dates,
        )
        self.cache.set(cache_key, data.model_dump())
        return data

    def get_technical_indicators(self, symbol: str) -> TechnicalIndicators:
        """Compute technical indicators."""
        cache_key = f"technical_{symbol}"
        cached = self.cache.get(cache_key)
        if cached:
            return TechnicalIndicators(**cached)

        hist_df = self.akshare.get_stock_history(symbol, self.settings.analysis.lookback_days)
        indicators = compute_all_indicators(hist_df, symbol)
        self.cache.set(cache_key, indicators.model_dump())
        return indicators

    def get_news(self, symbol: str) -> list[dict]:
        """Get recent news."""
        cache_key = f"news_{symbol}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        news = self.akshare.get_news(symbol, self.settings.analysis.news_count)
        self.cache.set(cache_key, news)
        return news

    def get_insider_trades(self, symbol: str) -> list[dict]:
        """Get insider trading data."""
        cache_key = f"insider_{symbol}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        trades = self.akshare.get_insider_trades(symbol)
        self.cache.set(cache_key, trades)
        return trades

    def get_risk_metrics(self, symbol: str) -> dict:
        """Compute risk metrics for a stock."""
        hist_df = self.akshare.get_stock_history(symbol, self.settings.analysis.lookback_days)
        if hist_df.empty:
            return {}
        returns = hist_df["close"].pct_change().dropna()
        return compute_risk_metrics(returns)

    def get_portfolio_state(self) -> PortfolioState:
        """Get current portfolio from CSV trade log with live prices."""
        # Build price lookup from cached snapshots
        price_lookup: dict[str, float] = {}
        csv_path = self.settings.base_dir / "portfolio.csv"
        if csv_path.exists():
            # First load without prices to get symbols
            raw = load_portfolio(csv_path)
            for pos in raw.positions:
                try:
                    snap = self.get_stock_snapshot(pos.symbol)
                    if snap.current_price > 0:
                        price_lookup[pos.symbol] = snap.current_price
                except Exception:
                    pass
            return load_portfolio(csv_path, price_lookup)

        # Fallback: use account_client if provided
        if self.account_client:
            try:
                return self.account_client.get_portfolio_state()
            except Exception as e:
                logger.warning("Account portfolio fetch failed: %s", e)

        return PortfolioState(
            total_value=self.settings.risk.total_capital,
            cash=self.settings.risk.total_capital,
        )

    def get_trade_history(self) -> list[dict]:
        """Get raw trade records from portfolio.csv."""
        csv_path = self.settings.base_dir / "portfolio.csv"
        return get_trade_history(csv_path)
