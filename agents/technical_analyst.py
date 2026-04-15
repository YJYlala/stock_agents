"""Technical Analyst agent."""

from stock_agents.agents.base import BaseAgent
from stock_agents.config.prompts import TECHNICAL_ANALYST


class TechnicalAnalyst(BaseAgent):
    name = "TechnicalAnalyst"
    role = "技术面分析师"

    def get_system_prompt(self) -> str:
        return TECHNICAL_ANALYST

    def gather_data(self, symbol: str, context: dict | None = None) -> dict:
        snapshot = self.data.get_stock_snapshot(symbol)
        indicators = self.data.get_technical_indicators(symbol)

        # Recent price action summary (last 20 days)
        recent_prices = []
        for bar in snapshot.history[-20:]:
            recent_prices.append({
                "date": bar.date.strftime("%Y-%m-%d"),
                "open": bar.open, "high": bar.high,
                "low": bar.low, "close": bar.close,
                "volume": bar.volume,
            })

        data = {
            "symbol": symbol,
            "name": snapshot.name,
            "current_price": snapshot.current_price,
            "change_pct": snapshot.change_pct,
            "indicators": indicators.model_dump(),
            "recent_prices": recent_prices,
        }
        # Include pre-computed technical signal classification
        if context and "quant_signals" in context:
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
        return data
