"""Market context data — macro, sector, and market breadth.

Fetched once per analysis run and cached. Provides the macroscopic context
that all agents need to reason about individual stocks in their broader
market environment.
"""

import asyncio
import logging
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


def _safe_call(func, *args, **kwargs):
    """Call an AKShare function, return None on failure."""
    try:
        result = func(*args, **kwargs)
        if isinstance(result, pd.DataFrame) and result.empty:
            return None
        return result
    except Exception as e:
        logger.warning("AKShare call %s failed: %s", func.__name__, e)
        return None


def get_market_indices(days: int = 5) -> dict:
    """Get Shanghai Composite and Shenzhen Component recent trend."""
    indices = {}
    for code, name in [("sh000001", "上证指数"), ("sz399001", "深证成指")]:
        df = _safe_call(ak.stock_zh_index_daily, symbol=code)
        if df is not None and len(df) >= days:
            recent = df.tail(days)
            closes = recent["close"].tolist()
            first, last = closes[0], closes[-1]
            pct_change = (last - first) / first * 100
            daily_changes = []
            for i in range(1, len(closes)):
                daily_changes.append(round((closes[i] - closes[i-1]) / closes[i-1] * 100, 2))
            indices[name] = {
                "latest_close": round(last, 2),
                f"{days}d_change_pct": round(pct_change, 2),
                "daily_changes": daily_changes,
                "trend": "上涨" if pct_change > 0.5 else ("下跌" if pct_change < -0.5 else "震荡"),
            }
    return indices


def get_industry_boards(top_n: int = 10) -> dict:
    """Get industry board rankings — top gainers and losers."""
    df = _safe_call(ak.stock_board_industry_name_em)
    if df is None:
        return {"top": [], "bottom": []}

    cols = ["板块名称", "涨跌幅", "领涨股票", "领涨股票-涨跌幅", "上涨家数", "下跌家数"]
    available_cols = [c for c in cols if c in df.columns]

    top = df.nlargest(top_n, "涨跌幅")[available_cols].to_dict("records")
    bottom = df.nsmallest(top_n, "涨跌幅")[available_cols].to_dict("records")
    return {"top": top, "bottom": bottom, "total_count": len(df)}


def get_concept_boards(top_n: int = 8) -> list[dict]:
    """Get today's hot concept themes."""
    df = _safe_call(ak.stock_board_concept_name_em)
    if df is None:
        return []

    cols = ["板块名称", "涨跌幅", "领涨股票"]
    available_cols = [c for c in cols if c in df.columns]
    return df.nlargest(top_n, "涨跌幅")[available_cols].to_dict("records")


def get_sector_fund_flows(top_n: int = 8) -> dict:
    """Get sector-level capital flows (主力资金)."""
    try:
        df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
    except Exception as e:
        logger.warning("Sector fund flow fetch failed: %s", e)
        return {"inflow": [], "outflow": []}

    if df is None or df.empty:
        return {"inflow": [], "outflow": []}

    cols = ["名称", "今日涨跌幅", "今日主力净流入-净额", "今日主力净流入-净占比"]
    available_cols = [c for c in cols if c in df.columns]

    inflow = df.nlargest(top_n, "今日主力净流入-净额")[available_cols].to_dict("records")
    outflow = df.nsmallest(top_n, "今日主力净流入-净额")[available_cols].to_dict("records")
    return {"inflow": inflow, "outflow": outflow}


def get_policy_news(date_str: str | None = None) -> list[dict]:
    """Get CCTV news headlines (央视新闻联播) — policy signal source."""
    if date_str is None:
        # Use yesterday if before 20:00 Beijing time (CCTV airs at 19:00)
        now = datetime.now()
        if now.hour < 20:
            date_str = (now - timedelta(days=1)).strftime("%Y%m%d")
        else:
            date_str = now.strftime("%Y%m%d")

    df = _safe_call(ak.news_cctv, date=date_str)
    if df is None:
        return []

    items = []
    for _, row in df.iterrows():
        title = str(row.get("title", ""))
        # Filter for finance/economy/policy relevant headlines
        keywords = ["经济", "金融", "贸易", "投资", "产业", "科技", "能源",
                     "制造", "基建", "房地产", "消费", "出口", "进口",
                     "央行", "利率", "汇率", "关税", "政策", "改革",
                     "国务院", "发改委", "证监会", "银保监", "财政"]
        if any(kw in title or kw in str(row.get("content", "")) for kw in keywords):
            items.append({
                "title": title,
                "content": str(row.get("content", ""))[:300],
            })
    return items[:10]  # Cap at 10 most relevant


def get_global_markets() -> dict:
    """Get international market data — US indices, forex, and global financial news."""
    results = {}

    # US major indices via Sina (fast, no pagination)
    us_items = []
    for code, name in [(".DJI", "道琼斯"), (".IXIC", "纳斯达克"), (".INX", "标普500")]:
        df = _safe_call(ak.index_us_stock_sina, symbol=code)
        if df is not None and not df.empty:
            row = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else None
            close = float(row["close"])
            change_pct = None
            if prev is not None:
                prev_close = float(prev["close"])
                if prev_close > 0:
                    change_pct = round((close - prev_close) / prev_close * 100, 2)
            us_items.append({
                "name": name,
                "latest": close,
                "change_pct": change_pct,
                "date": str(row["date"]),
            })
    if us_items:
        results["us_indices"] = us_items

    # USD/CNY forex
    fx = _safe_call(ak.fx_spot_quote)
    if fx is not None and not fx.empty:
        usd_row = fx[fx["货币对"].str.contains("USD/CNY", na=False)]
        if not usd_row.empty:
            r = usd_row.iloc[0]
            results["usd_cny"] = {
                "rate": r.get("买报价"),
            }

    # International financial news headlines
    global_news = _fetch_global_news()
    if global_news:
        results["global_news"] = global_news

    return results


def _fetch_global_news() -> list[str]:
    """Fetch international financial news from CLS (财联社) and WallStreetCN (华尔街见闻)."""
    import requests

    headlines: list[str] = []

    # Source 1: 华尔街见闻 global channel (best for intl finance in Chinese)
    try:
        url = "https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&limit=15"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        r.raise_for_status()
        items = r.json().get("data", {}).get("items", [])
        for it in items:
            text = it.get("content_text", "").strip()
            if text and len(text) > 10:
                headlines.append(text[:200])
    except Exception as e:
        logger.debug("WallStreetCN news fetch failed: %s", e)

    # Source 2: 财联社 flash news (mix of domestic + international)
    try:
        url = "https://www.cls.cn/nodeapi/updateTelegraphList?app=CailianpressWeb&os=web&sv=8.4.6&rn=20"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        r.raise_for_status()
        items = r.json().get("data", {}).get("roll_data", [])
        for it in items:
            text = it.get("content", "").strip()
            if text and len(text) > 10:
                # Filter for international/macro-relevant news
                intl_keywords = [
                    "美", "欧", "日", "英", "全球", "国际", "Fed", "美联储",
                    "关税", "贸易", "原油", "黄金", "白银", "铜", "美元",
                    "特朗普", "拜登", "外资", "OPEC", "央行", "利率",
                    "通胀", "CPI", "GDP", "PMI", "就业", "非农",
                ]
                if any(kw in text for kw in intl_keywords):
                    headlines.append(text[:200])
    except Exception as e:
        logger.debug("CLS news fetch failed: %s", e)

    # Deduplicate by first 30 chars
    seen = set()
    unique = []
    for h in headlines:
        key = h[:30]
        if key not in seen:
            seen.add(key)
            unique.append(h)

    return unique[:15]


def get_stock_industry_context(symbol: str) -> dict:
    """Get a stock's industry and that industry's current performance."""
    info = _safe_call(ak.stock_individual_info_em, symbol=symbol)
    if info is None:
        return {}

    industry_row = info.loc[info["item"] == "行业"]
    if industry_row.empty:
        return {}
    industry_name = str(industry_row["value"].values[0])

    result = {"industry_name": industry_name}

    # Look up this industry's board performance
    boards = _safe_call(ak.stock_board_industry_name_em)
    if boards is not None:
        match = boards[boards["板块名称"] == industry_name]
        if not match.empty:
            row = match.iloc[0]
            result["industry_change_pct"] = float(row.get("涨跌幅", 0))
            result["industry_rank"] = int(row.get("排名", 0))
            result["industry_total"] = len(boards)
            result["industry_advance"] = int(row.get("上涨家数", 0))
            result["industry_decline"] = int(row.get("下跌家数", 0))
            result["industry_leader"] = str(row.get("领涨股票", ""))

    return result


class MarketContext:
    """Fetches and caches market-wide context for a single analysis run."""

    def __init__(self):
        self._cache: dict | None = None
        self._industry_cache: dict[str, dict] = {}

    def get_context(self) -> dict:
        """Get or fetch the market-wide context (cached per run)."""
        if self._cache is not None:
            return self._cache

        logger.info("[MarketContext] Fetching market-wide context...")
        self._cache = self._fetch_all()
        logger.info("[MarketContext] Done — %d index(es), %d policy items",
                     len(self._cache.get("market_indices", {})),
                     len(self._cache.get("policy_news", [])))
        return self._cache

    def get_stock_industry(self, symbol: str) -> dict:
        """Get industry context for a specific stock (cached per symbol)."""
        if symbol not in self._industry_cache:
            self._industry_cache[symbol] = get_stock_industry_context(symbol)
        return self._industry_cache[symbol]

    def _fetch_all(self) -> dict:
        """Fetch all market context data. Uses threads for parallelism."""
        import concurrent.futures

        results = {}
        fetchers = {
            "market_indices": lambda: get_market_indices(5),
            "industry_boards": lambda: get_industry_boards(10),
            "hot_concepts": lambda: get_concept_boards(8),
            "sector_fund_flows": lambda: get_sector_fund_flows(8),
            "policy_news": lambda: get_policy_news(),
            "global_markets": lambda: get_global_markets(),
        }

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(fn): key for key, fn in fetchers.items()}
            for future in concurrent.futures.as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception as e:
                    logger.error("[MarketContext] %s failed: %s", key, e)
                    results[key] = {} if key != "policy_news" else []

        results["fetch_time"] = datetime.now().isoformat()
        return results

    def format_for_prompt(self, symbol: str | None = None) -> str:
        """Format market context as a concise text block for LLM prompts."""
        ctx = self.get_context()
        parts = []

        # Market trend
        indices = ctx.get("market_indices", {})
        if indices:
            parts.append("## 大盘走势")
            for name, data in indices.items():
                parts.append(
                    f"  {name}: {data['latest_close']} "
                    f"({data.get('5d_change_pct', 'N/A'):+.2f}% 近5日, 趋势: {data['trend']})"
                )

        # Global markets
        global_mkts = ctx.get("global_markets", {})
        us = global_mkts.get("us_indices", [])
        if us:
            parts.append("## 国际市场 (美股)")
            for idx in us:
                chg = idx.get("change_pct")
                chg_str = f"{chg:+.2f}%" if isinstance(chg, (int, float)) else "N/A"
                parts.append(f"  {idx['name']}: {idx.get('latest', 'N/A')} ({chg_str})")
        fx = global_mkts.get("usd_cny")
        if fx:
            parts.append(f"## 汇率: 美元/人民币 = {fx.get('rate', 'N/A')}")
        global_news = global_mkts.get("global_news", [])
        if global_news:
            parts.append("## 国际财经要闻 (华尔街见闻/财联社)")
            for i, headline in enumerate(global_news[:10], 1):
                parts.append(f"  {i}. {headline}")

        # Top/bottom sectors
        boards = ctx.get("industry_boards", {})
        if boards.get("top"):
            parts.append("## 行业涨幅前5")
            for b in boards["top"][:5]:
                parts.append(f"  {b['板块名称']}: {b['涨跌幅']:+.2f}%")
        if boards.get("bottom"):
            parts.append("## 行业跌幅前5")
            for b in boards["bottom"][:5]:
                parts.append(f"  {b['板块名称']}: {b['涨跌幅']:+.2f}%")

        # Hot concepts
        concepts = ctx.get("hot_concepts", [])
        if concepts:
            parts.append("## 热门概念板块")
            for c in concepts[:5]:
                parts.append(f"  {c['板块名称']}: {c['涨跌幅']:+.2f}%")

        # Fund flows
        flows = ctx.get("sector_fund_flows", {})
        if flows.get("inflow"):
            parts.append("## 主力资金净流入前3行业")
            for f in flows["inflow"][:3]:
                amt = f.get("今日主力净流入-净额", 0)
                amt_str = f"{amt/1e8:.1f}亿" if isinstance(amt, (int, float)) else str(amt)
                parts.append(f"  {f['名称']}: {amt_str}")

        # Policy news
        news = ctx.get("policy_news", [])
        if news:
            parts.append("## 政策/宏观新闻 (央视新闻联播)")
            for n in news[:5]:
                parts.append(f"  - {n['title']}")

        # Stock-specific industry
        if symbol:
            industry = self.get_stock_industry(symbol)
            if industry:
                parts.append(f"## 个股所属行业: {industry.get('industry_name', 'N/A')}")
                rank = industry.get("industry_rank")
                total = industry.get("industry_total")
                chg = industry.get("industry_change_pct")
                if rank and total:
                    parts.append(f"  行业排名: {rank}/{total} (今日涨跌: {chg:+.2f}%)")
                adv = industry.get("industry_advance", 0)
                dec = industry.get("industry_decline", 0)
                if adv or dec:
                    parts.append(f"  行业内上涨/下跌: {adv}/{dec}")

        return "\n".join(parts) if parts else "(市场数据暂不可用)"
