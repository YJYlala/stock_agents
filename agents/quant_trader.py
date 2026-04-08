"""Quantitative Trader agent - position sizing and statistical signals."""

from stock_agents.agents.base import BaseAgent
from stock_agents.config.prompts import QUANT_TRADER


class QuantTrader(BaseAgent):
    name = "QuantTrader"
    role = "量化交易员"

    def get_system_prompt(self) -> str:
        return QUANT_TRADER

    def gather_data(self, symbol: str, context: dict | None = None) -> dict:
        snapshot = self.data.get_stock_snapshot(symbol)
        risk = self.data.get_risk_metrics(symbol)
        portfolio = self.data.get_portfolio_state()
        indicators = self.data.get_technical_indicators(symbol)

        data = {
            "symbol": symbol,
            "name": snapshot.name,
            "current_price": snapshot.current_price,
            "change_pct": snapshot.change_pct,
            "risk_metrics": risk,
            "portfolio": {
                "total_value": portfolio.total_value,
                "cash": portfolio.cash,
                "position_count": len(portfolio.positions),
            },
            "max_single_position_pct": self.data.settings.risk.max_single_position_pct,
            "total_capital": self.data.settings.risk.total_capital,
            "technical": {
                "atr_14": indicators.atr_14,
                "rsi_14": indicators.rsi_14,
                "bollinger_upper": indicators.bollinger_upper,
                "bollinger_lower": indicators.bollinger_lower,
                "volume_ma_20": indicators.volume_ma_20,
                "vwap": indicators.vwap,
            },
        }

        # Include prior reports + debate for position sizing context
        if context:
            if "prior_reports" in context:
                summaries = []
                for r in context["prior_reports"]:
                    if hasattr(r, "agent_name"):
                        summaries.append({
                            "agent": r.agent_name,
                            "signal": r.signal,
                            "score": r.score,
                            "confidence": r.confidence,
                        })
                data["prior_analyst_signals"] = summaries

            if "debate_report" in context:
                data["debate_summary"] = context["debate_report"]

        return data
