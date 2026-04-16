"""Fund Manager agent - makes the final investment decision."""

import json
import logging

from stock_agents.llm import LLMClient
from stock_agents.llm import strip_markdown_fences
from stock_agents.config.prompts import FUND_MANAGER
from stock_agents.data.data_manager import DataManager
from stock_agents.models.signals import AgentReport, DebateReport, FinalDecision

logger = logging.getLogger(__name__)


class FundManagerError(ValueError):
    """Raised when the LLM fails to return a valid FinalDecision."""


class FundManager:
    """Final decision maker - synthesizes all agent reports."""

    name = "FundManager"
    role = "基金经理"

    def __init__(self, llm: LLMClient, data: DataManager):
        self.llm = llm
        self.data = data

    def decide(
        self,
        symbol: str,
        agent_reports: list[AgentReport],
        debate_report: DebateReport | None = None,
        trade_history: list[dict] | None = None,
        quant_signals: dict | None = None,
        market_context_text: str = "",
        curated_news: dict | None = None,
    ) -> FinalDecision:
        """Make final decision based on all agent inputs.

        Raises FundManagerError if the LLM fails or returns an incomplete result.
        Never returns a default/synthetic fallback decision.
        """
        logger.info("[FundManager] Making final decision for %s...", symbol)

        snapshot = self.data.get_stock_snapshot(symbol)
        portfolio = self.data.get_portfolio_state()

        # Helper for safe formatting
        def _fmt(v, fmt=",", default="N/A"):
            if v is None:
                return default
            try:
                if fmt == ",":
                    return f"{v:,.0f}"
                elif fmt == "%":
                    return f"{v:.1%}"
                elif fmt == ".2f":
                    return f"{v:.2f}"
                elif fmt == ".4f":
                    return f"{v:.4f}"
                elif fmt == "+.2f%":
                    return f"{v:+.2f}%"
                return str(v)
            except (TypeError, ValueError):
                return default

        # Build comprehensive user message
        user_msg = f"Stock: {symbol} ({snapshot.name})\n"
        user_msg += f"Current Price: {_fmt(snapshot.current_price, '.2f')}\n"
        user_msg += f"Market Cap: {_fmt(snapshot.market_cap)}\n\n"

        user_msg += "=== AGENT REPORTS ===\n\n"
        for report in agent_reports:
            user_msg += f"--- {report.agent_name} ({report.agent_role}) ---\n"
            user_msg += f"Signal: {report.signal} | Score: {_fmt(report.score, '.2f')}/10 | Confidence: {_fmt(report.confidence, '.2f')}\n"
            user_msg += f"Reasoning: {report.reasoning}\n"
            user_msg += f"Key factors: {', '.join(report.key_factors)}\n"
            user_msg += f"Risks: {', '.join(report.risks)}\n\n"

        if debate_report:
            user_msg += "=== BULL/BEAR DEBATE ===\n"
            user_msg += f"Bull Score: {_fmt(debate_report.bull_score, '.2f')}/10\n"
            user_msg += f"Bull Thesis: {debate_report.bull_thesis}\n\n"
            user_msg += f"Bear Score: {_fmt(debate_report.bear_score, '.2f')}/10\n"
            user_msg += f"Bear Thesis: {debate_report.bear_thesis}\n\n"
            user_msg += f"Net Conviction: {_fmt(debate_report.net_conviction, '.2f')}\n\n"

        if quant_signals:
            user_msg += "=== PRE-COMPUTED QUANT ENGINE SIGNALS ===\n"
            qs = quant_signals.get("quant_signal", {})
            user_msg += f"Composite Score: {_fmt(qs.get('composite_score'), '.2f')}/10\n"
            user_msg += f"Model Signal: {qs.get('signal', 'N/A')}\n"
            user_msg += f"Kelly Fraction: {_fmt(qs.get('kelly_fraction'), '.4f')} (Half-Kelly: {_fmt(qs.get('half_kelly'), '.4f')})\n"
            user_msg += f"Win Probability: {_fmt(qs.get('win_probability'), '%')}\n"
            user_msg += f"Risk/Reward Ratio: {_fmt(qs.get('risk_reward_ratio'), '.2f')}\n"
            pos_pct = qs.get('position_size_pct')
            user_msg += f"Recommended Position: {_fmt(pos_pct, '%')} ({qs.get('position_size_shares', 'N/A')} shares)\n\n"

            rs = quant_signals.get("risk_signal", {})
            user_msg += f"Risk Approved: {rs.get('risk_approved', 'N/A')}\n"
            user_msg += f"Stop Loss: {rs.get('stop_loss_price', 'N/A')}\n"
            user_msg += f"Max Loss: {rs.get('max_loss_amount', 'N/A')} CNY\n"
            veto_reasons = rs.get("veto_reasons", [])
            if veto_reasons:
                user_msg += f"Veto Reasons: {', '.join(veto_reasons)}\n"
            user_msg += "\n"

        user_msg += "=== PORTFOLIO STATE ===\n"

        if market_context_text:
            user_msg += "=== MARKET CONTEXT (宏观/行业/板块) ===\n"
            user_msg += market_context_text + "\n\n"

        if curated_news:
            user_msg += "=== AI CURATED NEWS DIGEST ===\n"
            user_msg += f"宏观影响: {curated_news.get('macro_relevance', 'N/A')}\n"
            user_msg += f"行业展望: {curated_news.get('sector_outlook', 'N/A')}\n"
            events = curated_news.get("company_events", [])
            if events:
                user_msg += "公司事件:\n"
                for e in events:
                    user_msg += f"  - {e}\n"
            risks = curated_news.get("risk_flags", [])
            if risks:
                user_msg += "风险提示:\n"
                for r in risks:
                    user_msg += f"  ⚠ {r}\n"
            user_msg += f"新闻情绪: {curated_news.get('sentiment_summary', 'N/A')}\n\n"

        user_msg += "=== PORTFOLIO STATE (continued) ===\n"
        user_msg += f"Total Value: {_fmt(portfolio.total_value)}\n"
        user_msg += f"Cash: {_fmt(portfolio.cash)}\n"
        user_msg += f"Existing Positions: {len(portfolio.positions)}\n"
        for pos in portfolio.positions:
            pnl_str = _fmt(pos.unrealized_pnl_pct, '+.2f%')
            user_msg += f"  - {pos.symbol} ({pos.name}): {pos.shares} shares, weight={pos.weight_pct}%, PnL={pnl_str}\n"
        user_msg += "\n"

        user_msg += "=== RISK LIMITS ===\n"
        user_msg += f"Max Single Position: {self.data.settings.risk.max_single_position_pct * 100}%\n"
        user_msg += f"Max Drawdown: {self.data.settings.risk.max_drawdown_pct * 100}%\n\n"

        if trade_history:
            user_msg += "=== TRADE HISTORY ===\n"
            for t in trade_history:
                user_msg += f"  {t['date']} {t['action'].upper()} {t['shares']} x {t['symbol']}({t['name']}) @ {t['price']} (commission={t['commission']}, note={t['note']})\n"
            user_msg += "\n"

        user_msg += (
            "Now provide your COMPLETE final decision as JSON. "
            "You MUST include ALL required fields: action (BUY/SELL/HOLD), confidence (0-1), "
            "target_price, stop_loss, position_size_pct (0-100 scale), position_size_shares, "
            "fundamental_score, technical_score, sentiment_score, summary, decision_methodology, "
            "bull_case, bear_case, risk_assessment."
        )

        # Call LLM — raise on failure, do NOT fall back to synthesis
        result = self.llm.analyze(
            system_prompt=FUND_MANAGER,
            user_message=user_msg,
        )

        # Parse JSON if returned as string
        if isinstance(result, str):
            text = strip_markdown_fences(result)
            try:
                result = json.loads(text)
            except json.JSONDecodeError as e:
                raise FundManagerError(
                    f"[FundManager] LLM returned non-JSON string for {symbol}: {e} | raw={text[:500]}"
                ) from e

        if not isinstance(result, dict) or not result:
            raise FundManagerError(
                f"[FundManager] LLM returned no usable result for {symbol} "
                f"(type={type(result).__name__}, value={str(result)[:200]})"
            )

        # Validate required fields — fail loudly rather than silently produce defaults
        required = ["action", "confidence", "position_size_pct"]
        missing = [k for k in required if result.get(k) is None]
        if missing:
            raise FundManagerError(
                f"[FundManager] LLM response missing required fields {missing} for {symbol} | keys={list(result.keys())}"
            )

        action = result["action"].upper().strip()
        if action not in ("BUY", "SELL", "HOLD"):
            raise FundManagerError(
                f"[FundManager] LLM returned invalid action '{action}' for {symbol} — must be BUY/SELL/HOLD"
            )

        # Normalize position_size_pct: LLM often returns percent units (e.g. 8.5 for 8.5%)
        pct = float(result["position_size_pct"])
        if pct > 1.0:
            pct = pct / 100.0

        # Shares: use LLM value if provided, otherwise compute from pct
        shares = result.get("position_size_shares")
        price = snapshot.current_price
        if not shares and pct > 0 and price and price > 0:
            total = portfolio.total_value or 0
            position_value = total * pct
            shares = int(position_value / price) // 100 * 100
        shares = int(shares or 0)

        def _opt_float(key):
            v = result.get(key)
            if v is None:
                return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None

        return FinalDecision(
            symbol=symbol,
            name=snapshot.name,
            current_price=snapshot.current_price,
            action=action,
            confidence=float(result["confidence"]),
            target_price=_opt_float("target_price"),
            stop_loss=_opt_float("stop_loss"),
            position_size_pct=pct,
            position_size_shares=shares,
            fundamental_score=_opt_float("fundamental_score"),
            technical_score=_opt_float("technical_score"),
            sentiment_score=_opt_float("sentiment_score"),
            summary=result.get("summary", ""),
            decision_methodology=result.get("decision_methodology", ""),
            bull_case=result.get("bull_case", ""),
            bear_case=result.get("bear_case", ""),
            risk_assessment=result.get("risk_assessment", ""),
            agent_reports=agent_reports,
            debate_report=debate_report,
            llm_model=getattr(self.llm, "model_label", ""),
        )

