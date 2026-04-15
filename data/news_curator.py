"""AI news curator — filters and classifies raw news for agent consumption.

Uses a cheap LLM call to transform raw company news + market context into
a structured digest that agents can reason about effectively.
"""

import json
import logging

logger = logging.getLogger(__name__)

_CURATOR_SYSTEM_PROMPT = """你是一位专业的A股市场新闻分析员。你的任务是对原始新闻进行筛选和分类，为投资分析师提供结构化的新闻摘要。

规则：
1. 过滤掉广告、软文、无关内容
2. 提取关键金融事件（财报、政策、并购、内部交易）
3. 将新闻分为：宏观/行业/公司三个层面
4. 为每条相关新闻添加一句话影响评估
5. 如果没有相关新闻，直接说"无重大相关新闻"
6. 从国际、宏观、行业、公司四个维度分析新闻对该股票的影响
7. 必须用中文回答，输出严格JSON格式"""

_CURATOR_USER_TEMPLATE = """请分析以下新闻，为股票 {symbol}({name}) 生成结构化新闻摘要。

## 公司新闻
{company_news}

## 市场大盘信息（含国际市场）
{market_summary}

## 该股所属行业: {industry}

请输出以下JSON格式（不要包含markdown代码块标记）：
{{
  "macro_relevance": "一句话总结当前宏观环境对该股的影响，包含国际市场因素，如无相关则写'当前宏观环境无直接影响'",
  "sector_outlook": "该股所属行业当日表现和资金流向总结",
  "company_events": ["公司层面的重要事件列表，每条一句话"],
  "risk_flags": ["需要关注的风险点列表"],
  "sentiment_summary": "整体新闻情绪：偏多/偏空/中性，一句话说明原因",
  "init_summary": "200字以内的综合摘要：从国际→宏观→行业→公司四个维度，描述当前新闻环境对该股的整体影响，作为情绪分析师的输入",
  "useful_news": ["从原始新闻中筛选出的、对投资决策有实际价值的新闻标题+一句话要点，最多8条"]
}}"""


def curate_news(
    llm,
    symbol: str,
    name: str,
    raw_news: list[dict],
    market_context_text: str,
    industry_name: str = "",
    announcements: list[dict] | None = None,
) -> dict:
    """Use LLM to curate raw news into a structured digest.

    Args:
        llm: Any LLM client with .analyze() method
        symbol: Stock code
        name: Stock name
        raw_news: List of news dicts from AKShare
        market_context_text: Pre-formatted market context string
        industry_name: Stock's industry name
        announcements: Company official announcements (公告)

    Returns:
        Structured digest dict, or a fallback dict on failure.
    """
    if not raw_news and not market_context_text and not announcements:
        return _empty_digest("无新闻数据")

    # Format company news for the prompt
    news_text = ""
    if raw_news:
        for i, n in enumerate(raw_news[:12], 1):
            title = n.get("title", n.get("新闻标题", ""))
            content = n.get("content", n.get("新闻内容", ""))[:200]
            source = n.get("source", n.get("文章来源", ""))
            news_text += f"{i}. [{source}] {title}\n   {content}\n"
    else:
        news_text = "无公司相关新闻"

    # Append company announcements (公告)
    if announcements:
        news_text += "\n\n## 公司官方公告（近90天）\n"
        for i, ann in enumerate(announcements[:10], 1):
            title = ann.get("title", ann.get("公告标题", ""))
            date = ann.get("date", ann.get("公告日期", ""))
            cat = ann.get("type", ann.get("公告类型", ""))
            news_text += f"{i}. [{date}] {title} ({cat})\n"

    user_msg = _CURATOR_USER_TEMPLATE.format(
        symbol=symbol,
        name=name or symbol,
        company_news=news_text,
        market_summary=market_context_text or "(市场数据暂不可用)",
        industry=industry_name or "未知",
    )

    try:
        result = llm.analyze(
            system_prompt=_CURATOR_SYSTEM_PROMPT,
            user_message=user_msg,
            max_retries=2,
        )

        if isinstance(result, dict):
            return _validate_digest(result)
        if isinstance(result, str):
            parsed = json.loads(result)
            return _validate_digest(parsed)
    except Exception as e:
        logger.warning("[NewsCurator] LLM curation failed for %s: %s", symbol, e)

    # Fallback: basic extraction without AI
    return _fallback_digest(raw_news, market_context_text, industry_name)


def _validate_digest(d: dict) -> dict:
    """Ensure the digest has all required fields."""
    return {
        "macro_relevance": d.get("macro_relevance", ""),
        "sector_outlook": d.get("sector_outlook", ""),
        "company_events": d.get("company_events", []),
        "risk_flags": d.get("risk_flags", []),
        "sentiment_summary": d.get("sentiment_summary", "中性"),
        "init_summary": d.get("init_summary", ""),
        "useful_news": d.get("useful_news", []),
    }


def _empty_digest(reason: str) -> dict:
    return {
        "macro_relevance": reason,
        "sector_outlook": "",
        "company_events": [],
        "risk_flags": [],
        "sentiment_summary": "中性 — 无充分信息判断",
        "init_summary": reason,
        "useful_news": [],
    }


def _fallback_digest(
    raw_news: list[dict],
    market_text: str,
    industry: str,
) -> dict:
    """Basic non-AI digest when LLM fails."""
    events = []
    useful = []
    for n in raw_news[:6]:
        title = n.get("title", n.get("新闻标题", ""))
        if title:
            events.append(title)
            useful.append(title)

    return {
        "macro_relevance": "LLM新闻分析不可用，请参考原始市场数据自行判断",
        "sector_outlook": f"所属行业: {industry}" if industry else "",
        "company_events": events,
        "risk_flags": [],
        "sentiment_summary": "中性 — AI分析不可用",
        "init_summary": "AI新闻摘要不可用，请自行分析原始数据",
        "useful_news": useful,
    }
