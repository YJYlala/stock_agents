"""Fundamental Analyst agent."""

from stock_agents.agents.base import BaseAgent
from stock_agents.config.prompts import FUNDAMENTAL_ANALYST


class FundamentalAnalyst(BaseAgent):
    name = "FundamentalAnalyst"
    role = "基本面分析师"

    def get_system_prompt(self) -> str:
        return FUNDAMENTAL_ANALYST

    def gather_data(self, symbol: str, context: dict | None = None) -> dict:
        snapshot = self.data.get_stock_snapshot(symbol)
        financials = self.data.get_financial_data(symbol)
        data = {
            "symbol": symbol,
            "name": snapshot.name,
            "current_price": snapshot.current_price,
            "market_cap": snapshot.market_cap,
            "pe_ratio": snapshot.pe_ratio,
            "pb_ratio": snapshot.pb_ratio,
            "revenue": financials.revenue,
            "net_profit": financials.net_profit,
            "total_assets": financials.total_assets,
            "total_liabilities": financials.total_liabilities,
            "total_equity": financials.total_equity,
            "operating_cash_flow": financials.operating_cash_flow,
            "eps": financials.eps,
            "roe": financials.roe,
            "debt_to_equity": financials.debt_to_equity,
            "gross_margin": financials.gross_margin,
            "net_margin": financials.net_margin,
            "revenue_growth": financials.revenue_growth,
            "profit_growth": financials.profit_growth,
            "report_dates": financials.report_dates,
        }
        # Include pre-computed quant signals (fundamental_signal is the key section)
        if context and "quant_signals" in context:
            data["fundamental_signal"] = context["quant_signals"].get("fundamental_signal", {})
        if context and "portfolio" in context:
            portfolio = context["portfolio"]
            data["my_portfolio"] = {"cash": portfolio["cash"], "total_value": portfolio["total_value"]}
            for pos in portfolio.get("positions", []):
                if pos["symbol"] == symbol:
                    data["my_position"] = pos
                    break
        return data
