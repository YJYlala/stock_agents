"""Risk Manager agent - enforces risk limits, has veto power."""

from stock_agents.agents.base import BaseAgent
from stock_agents.config.prompts import RISK_MANAGER


class RiskManager(BaseAgent):
    name = "RiskManager"
    role = "风险管理官"

    def get_system_prompt(self) -> str:
        return RISK_MANAGER

    def gather_data(self, symbol: str, context: dict | None = None) -> dict:
        snapshot = self.data.get_stock_snapshot(symbol)
        risk = self.data.get_risk_metrics(symbol)
        portfolio = self.data.get_portfolio_state()
        indicators = self.data.get_technical_indicators(symbol)

        positions_data = []
        for pos in portfolio.positions:
            positions_data.append({
                "symbol": pos.symbol,
                "name": pos.name,
                "shares": pos.shares,
                "market_value": pos.market_value,
                "weight_pct": pos.weight_pct,
                "unrealized_pnl_pct": pos.unrealized_pnl_pct,
            })

        return {
            "symbol": symbol,
            "name": snapshot.name,
            "current_price": snapshot.current_price,
            "atr_14": indicators.atr_14,
            "volatility": risk.get("volatility_annual", 0),
            "max_drawdown": risk.get("max_drawdown", 0),
            "risk_metrics": risk,
            "portfolio": {
                "total_value": portfolio.total_value,
                "cash": portfolio.cash,
                "positions": positions_data,
                "total_unrealized_pnl": portfolio.total_unrealized_pnl,
            },
            "risk_limits": {
                "max_single_position_pct": self.data.settings.risk.max_single_position_pct,
                "max_sector_pct": self.data.settings.risk.max_sector_pct,
                "max_drawdown_pct": self.data.settings.risk.max_drawdown_pct,
            },
            # Pre-computed risk signal (Taleb + Markowitz framework)
            "risk_signal": context.get("quant_signals", {}).get("risk_signal", {}) if context else {},
            "quant_signal": context.get("quant_signals", {}).get("quant_signal", {}) if context else {},
        }
