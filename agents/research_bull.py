"""Bull Researcher agent - builds the strongest bull case."""

from stock_agents.agents.base import BaseAgent
from stock_agents.config.prompts import BULL_RESEARCHER


class BullResearcher(BaseAgent):
    name = "BullResearcher"
    role = "多头研究员"

    def get_system_prompt(self) -> str:
        return BULL_RESEARCHER

    def gather_data(self, symbol: str, context: dict | None = None) -> dict:
        snapshot = self.data.get_stock_snapshot(symbol)
        financial = self.data.get_financial_data(symbol)
        indicators = self.data.get_technical_indicators(symbol)

        data = {
            "symbol": symbol,
            "name": snapshot.name,
            "current_price": snapshot.current_price,
            "market_cap": snapshot.market_cap,
            "change_pct": snapshot.change_pct,
            "financial_summary": {
                "revenue_growth": financial.revenue_growth,
                "profit_growth": financial.profit_growth,
                "gross_margin": financial.gross_margin,
                "net_margin": financial.net_margin,
                "roe": financial.roe,
                "pe_ratio": snapshot.pe_ratio,
                "pb_ratio": snapshot.pb_ratio,
            },
            "technical_summary": {
                "trend": indicators.trend,
                "rsi_14": indicators.rsi_14,
                "macd_hist": indicators.macd_hist,
                "ma_5": indicators.ma_5,
                "ma_20": indicators.ma_20,
                "ma_60": indicators.ma_60,
            },
        }

        # Include pre-computed quant signals for advocacy
        if context and "quant_signals" in context:
            data["fundamental_signal"] = context["quant_signals"].get("fundamental_signal", {})
            data["technical_signal"] = context["quant_signals"].get("technical_signal", {})
            data["quant_signal"] = context["quant_signals"].get("quant_signal", {})

        # Include prior reports summaries for synthesis
        if context and "prior_reports" in context:
            summaries = []
            for r in context["prior_reports"]:
                if hasattr(r, "agent_name"):
                    summaries.append({
                        "agent": r.agent_name,
                        "signal": r.signal,
                        "score": r.score,
                        "key_factors": r.key_factors[:5],
                    })
            data["prior_analyst_signals"] = summaries

        if context and "market_context" in context:
            data["market_context"] = context["market_context"]
        if context and "curated_news" in context:
            data["curated_news"] = context["curated_news"]
        if context and "announcements" in context:
            data["announcements"] = context["announcements"]
        return data
