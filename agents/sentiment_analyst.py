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
            "recent_news": news[:15],
            "insider_trades": insider[:10],
        }
        if context and "portfolio" in context:
            portfolio = context["portfolio"]
            data["my_portfolio"] = {"cash": portfolio["cash"], "total_value": portfolio["total_value"]}
            for pos in portfolio.get("positions", []):
                if pos["symbol"] == symbol:
                    data["my_position"] = pos
                    break
        return data
