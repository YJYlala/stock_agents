"""DCF valuation adapter - wraps the existing DCFModel."""

import logging
import sys
from pathlib import Path

from stock_agents.models.market_data import FinancialData, StockSnapshot

logger = logging.getLogger(__name__)

# Add the skill path to import the existing DCFModel
_SKILL_PATH = str(Path(__file__).resolve().parent.parent.parent / ".agents" / "skills" / "creating-financial-models")


def run_dcf_valuation(financial: FinancialData, snapshot: StockSnapshot) -> dict:
    """Run DCF valuation using the existing DCFModel.

    Returns dict with intrinsic value, upside/downside, and summary.
    """
    try:
        if _SKILL_PATH not in sys.path:
            sys.path.insert(0, _SKILL_PATH)
        from dcf_model import DCFModel

        model = DCFModel(company_name=snapshot.name or snapshot.symbol)

        # Set historical financials
        if financial.revenue and financial.net_profit:
            revenue = financial.revenue[:5]
            # Estimate EBITDA as ~1.3x net profit (rough approximation)
            ebitda = [p * 1.3 for p in financial.net_profit[:5]]
            # Estimate capex as ~5% of revenue
            capex = [r * 0.05 for r in revenue]
            # Estimate NWC change as ~2% of revenue
            nwc = [r * 0.02 for r in revenue]

            if len(revenue) >= 2:
                model.set_historical_financials(
                    revenue=revenue,
                    ebitda=ebitda,
                    capex=capex,
                    net_working_capital_change=nwc,
                )

        # Set assumptions
        rev_growth = financial.revenue_growth / 100 if financial.revenue_growth else 0.05
        model.set_projection_assumptions(
            projection_years=5,
            revenue_growth_rates=[rev_growth] * 5,
            ebitda_margin=financial.net_margin * 1.3 / 100 if financial.net_margin else 0.15,
            capex_pct_revenue=0.05,
            nwc_pct_revenue=0.02,
            tax_rate=0.25,
        )

        # WACC (China context)
        model.set_wacc(
            risk_free_rate=0.025,  # China 10-year bond
            equity_risk_premium=0.065,
            beta=1.0,
            cost_of_debt=0.04,
            tax_rate=0.25,
            debt_weight=financial.debt_to_equity / (100 + financial.debt_to_equity) if financial.debt_to_equity else 0.3,
        )

        # Calculate
        model.calculate_dcf(terminal_growth_rate=0.03)

        results = model.valuation_results
        ev = results.get("enterprise_value", 0)
        eq = results.get("equity_value", 0)

        # Estimate per-share value
        # Use market cap / current price as proxy for shares outstanding
        shares_outstanding = snapshot.market_cap / snapshot.current_price if snapshot.current_price > 0 else 1
        intrinsic_per_share = eq / shares_outstanding if shares_outstanding > 0 else 0
        upside = (intrinsic_per_share - snapshot.current_price) / snapshot.current_price * 100 if snapshot.current_price > 0 else 0

        return {
            "enterprise_value": ev,
            "equity_value": eq,
            "intrinsic_per_share": round(intrinsic_per_share, 2),
            "current_price": snapshot.current_price,
            "upside_pct": round(upside, 1),
            "wacc": results.get("wacc", 0),
            "terminal_value": results.get("terminal_value", 0),
        }

    except Exception as e:
        logger.warning("DCF valuation failed: %s", e)
        return {"error": str(e)}
