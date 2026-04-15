"""Sentiment Analyst agent."""

from stock_agents.agents.base import BaseAgent
from stock_agents.config.prompts import SENTIMENT_ANALYST


class SentimentAnalyst(BaseAgent):
    name = "SentimentAnalyst"
    role = "情绪面分析师"

    def get_system_prompt(self) -> str:
        return SENTIMENT_ANALYST

    def gather_data(self, symbol: str, context: dict | None = None) -> dict:
        snapshot = self.data.get_stock_snapshot(symbol)
        news = self.data.get_news(symbol)
        insider = self.data.get_insider_trades(symbol)

        data = {
            "symbol": symbol,
            "name": snapshot.name,
            "current_price": snapshot.current_price,
            "change_pct": snapshot.change_pct,
            "insider_trades": insider[:5],
        }

        # Two-stage news flow: use curated news if available, fallback to raw
        if context and "curated_news" in context:
            curated = context["curated_news"]
            data["curated_news"] = curated
            # Use AI-filtered useful_news instead of raw top-8
            useful = curated.get("useful_news", [])
            data["recent_news"] = useful if useful else news[:8]
            # Include curator's init_summary for smarter second-pass analysis
            if curated.get("init_summary"):
                data["news_curator_summary"] = curated["init_summary"]
        else:
            data["recent_news"] = news[:8]

        # Include pre-computed quant signals for macro context
        if context and "quant_signals" in context:
            data["fundamental_signal"] = context["quant_signals"].get("fundamental_signal", {})
            data["technical_signal"] = context["quant_signals"].get("technical_signal", {})
        if context and "portfolio" in context:
            portfolio = context["portfolio"]
            data["my_portfolio"] = {"cash": portfolio["cash"], "total_value": portfolio["total_value"]}
            for pos in portfolio.get("positions", []):
                if pos["symbol"] == symbol:
                    data["my_position"] = pos
                    break
        if context and "market_context" in context:
            data["market_context"] = context["market_context"]
        if context and "announcements" in context:
            data["announcements"] = context["announcements"]
        return data
