"""AKShare data client for A-share market data."""

import logging
import os
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)

# Fix SSL issues when Clash proxy intercepts HTTPS traffic.
# Clash's TLS handling causes UNEXPECTED_EOF_WHILE_READING errors with some
# domestic finance APIs. We patch requests.Session to use a permissive TLS context.
import ssl
import urllib3
import requests as _requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class _TLSAdapter(HTTPAdapter):
    """HTTPS adapter that works through Clash proxy's TLS interception."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


_orig_session_init = _requests.Session.__init__


def _patched_session_init(self, *a, **kw):
    _orig_session_init(self, *a, **kw)
    self.mount("https://", _TLSAdapter())
    self.verify = False


_requests.Session.__init__ = _patched_session_init


class AKShareClient:
    """Fetches A-share data via the akshare Python package."""

    def _normalize_symbol(self, symbol: str) -> str:
        """Ensure symbol is clean digits only."""
        return symbol.strip().replace("SH.", "").replace("SZ.", "")

    def _to_163_symbol(self, symbol: str) -> str:
        """Convert pure digits to 163-style symbol (sh600519 / sz000858)."""
        symbol = self._normalize_symbol(symbol)
        prefix = "sh" if symbol.startswith("6") else "sz"
        return f"{prefix}{symbol}"

    def get_stock_history(self, symbol: str, days: int = 250) -> pd.DataFrame:
        """Get historical OHLCV data. Uses NetEase/163 source (bypasses eastmoney SSL issues)."""
        symbol = self._normalize_symbol(symbol)
        try:
            sym_163 = self._to_163_symbol(symbol)
            df = ak.stock_zh_a_daily(symbol=sym_163, adjust="qfq")
            if df is None or df.empty:
                logger.warning("No history data for %s", symbol)
                return pd.DataFrame()
            # 163 source columns: date, open, high, low, close, volume, amount (=turnover), outstanding_share, turnover (=ratio)
            # Keep only what we need, using positional if names collide
            out = pd.DataFrame()
            out["date"] = df["date"]
            out["open"] = df["open"]
            out["high"] = df["high"]
            out["low"] = df["low"]
            out["close"] = df["close"]
            out["volume"] = df["volume"]
            # "amount" in 163 source is actually the turnover amount in CNY
            if "amount" in df.columns:
                col = df["amount"]
                # If there are duplicate 'amount' columns, take the first one
                if isinstance(col, pd.DataFrame):
                    col = col.iloc[:, 0]
                out["amount"] = col
            else:
                out["amount"] = 0.0
            out["date"] = pd.to_datetime(out["date"])
            out = out.sort_values("date").tail(days).reset_index(drop=True)
            return out
        except Exception as e:
            logger.error("Failed to get history for %s: %s", symbol, e)
            return pd.DataFrame()

    def get_realtime_quote(self, symbol: str) -> dict:
        """Get real-time quote for a stock using individual stock API (fast)."""
        symbol = self._normalize_symbol(symbol)
        try:
            # Use individual stock info instead of fetching all stocks
            df = ak.stock_individual_info_em(symbol=symbol)
            info = {}
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    key = str(row.iloc[0]) if len(row) > 0 else ""
                    val = row.iloc[1] if len(row) > 1 else ""
                    info[key] = val

            # Get latest price from history (last bar)
            hist = self.get_stock_history(symbol, days=5)
            current_price = 0.0
            change_pct = 0.0
            if not hist.empty:
                current_price = float(hist["close"].iloc[-1])
                if len(hist) >= 2:
                    prev = float(hist["close"].iloc[-2])
                    change_pct = (current_price - prev) / prev * 100 if prev > 0 else 0

            return {
                "symbol": symbol,
                "name": str(info.get("股票简称", info.get("名称", ""))),
                "current_price": current_price,
                "change_pct": round(change_pct, 2),
                "volume": 0,
                "amount": 0,
                "market_cap": float(info.get("总市值", 0) or 0),
                "pe_ratio": float(info.get("市盈率(动态)", 0) or 0) or None,
                "pb_ratio": float(info.get("市净率", 0) or 0) or None,
            }
        except Exception as e:
            logger.error("Failed to get realtime quote for %s: %s", symbol, e)
            return {}

    def get_income_statement(self, symbol: str) -> pd.DataFrame:
        """Get income statement data."""
        symbol = self._normalize_symbol(symbol)
        try:
            df = ak.stock_financial_report_sina(stock=symbol, symbol="利润表")
            if df is None or df.empty:
                return pd.DataFrame()
            return df
        except Exception as e:
            logger.error("Failed to get income statement for %s: %s", symbol, e)
            return pd.DataFrame()

    def get_balance_sheet(self, symbol: str) -> pd.DataFrame:
        """Get balance sheet data."""
        symbol = self._normalize_symbol(symbol)
        try:
            df = ak.stock_financial_report_sina(stock=symbol, symbol="资产负债表")
            if df is None or df.empty:
                return pd.DataFrame()
            return df
        except Exception as e:
            logger.error("Failed to get balance sheet for %s: %s", symbol, e)
            return pd.DataFrame()

    def get_cash_flow(self, symbol: str) -> pd.DataFrame:
        """Get cash flow statement data."""
        symbol = self._normalize_symbol(symbol)
        try:
            df = ak.stock_financial_report_sina(stock=symbol, symbol="现金流量表")
            if df is None or df.empty:
                return pd.DataFrame()
            return df
        except Exception as e:
            logger.error("Failed to get cash flow for %s: %s", symbol, e)
            return pd.DataFrame()

    def get_financial_metrics(self, symbol: str) -> dict:
        """Get key financial metrics."""
        symbol = self._normalize_symbol(symbol)
        try:
            df = ak.stock_financial_analysis_indicator(symbol=symbol)
            if df is None or df.empty:
                return {}
            latest = df.iloc[0]
            return {
                "roe": float(latest.get("净资产收益率(%)", 0) or 0),
                "gross_margin": float(latest.get("销售毛利率(%)", 0) or 0),
                "net_margin": float(latest.get("销售净利率(%)", 0) or 0),
                "debt_to_equity": float(latest.get("资产负债率(%)", 0) or 0),
                "eps": float(latest.get("摊薄每股收益(元)", 0) or 0),
                "report_dates": df["日期"].head(8).tolist() if "日期" in df.columns else [],
            }
        except Exception as e:
            logger.error("Failed to get financial metrics for %s: %s", symbol, e)
            return {}

    def get_news(self, symbol: str, count: int = 20) -> list[dict]:
        """Get recent news for a stock."""
        symbol = self._normalize_symbol(symbol)
        try:
            df = ak.stock_news_em(symbol=symbol)
            if df is None or df.empty:
                return []
            items = []
            for _, row in df.head(count).iterrows():
                items.append({
                    "title": str(row.get("新闻标题", "")),
                    "content": str(row.get("新闻内容", ""))[:500],
                    "time": str(row.get("发布时间", "")),
                    "source": str(row.get("文章来源", "")),
                })
            return items
        except Exception as e:
            logger.error("Failed to get news for %s: %s", symbol, e)
            return []

    def get_insider_trades(self, symbol: str) -> list[dict]:
        """Get insider trading data."""
        symbol = self._normalize_symbol(symbol)
        try:
            # Use stock individual info for insider trades
            df = ak.stock_inner_trade_xq(symbol=symbol)
            if df is None or df.empty:
                return []
            items = []
            for _, row in df.head(20).iterrows():
                items.append({k: str(v) for k, v in row.items()})
            return items
        except Exception:
            return []
