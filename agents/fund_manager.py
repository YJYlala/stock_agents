"""Fund Manager agent - makes the final investment decision."""

import json
import logging

from stock_agents.llm import LLMClient
from stock_agents.config.prompts import FUND_MANAGER
from stock_agents.data.data_manager import DataManager
from stock_agents.models.signals import AgentReport, DebateReport, FinalDecision

logger = logging.getLogger(__name__)


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
    ) -> FinalDecision:
        """Make final decision based on all agent inputs."""
        logger.info("[FundManager] Making final decision for %s...", symbol)

        snapshot = self.data.get_stock_snapshot(symbol)
        portfolio = self.data.get_portfolio_state()

        # Build comprehensive user message
        user_msg = f"Stock: {symbol} ({snapshot.name})\n"
        user_msg += f"Current Price: {snapshot.current_price}\n"
        user_msg += f"Market Cap: {snapshot.market_cap:,.0f}\n\n"

        user_msg += "=== AGENT REPORTS ===\n\n"
        for report in agent_reports:
            user_msg += f"--- {report.agent_name} ({report.agent_role}) ---\n"
            user_msg += f"Signal: {report.signal} | Score: {report.score}/10 | Confidence: {report.confidence}\n"
            user_msg += f"Reasoning: {report.reasoning}\n"
            user_msg += f"Key factors: {', '.join(report.key_factors)}\n"
            user_msg += f"Risks: {', '.join(report.risks)}\n\n"

        if debate_report:
            user_msg += "=== BULL/BEAR DEBATE ===\n"
            user_msg += f"Bull Score: {debate_report.bull_score}/10\n"
            user_msg += f"Bull Thesis: {debate_report.bull_thesis}\n\n"
            user_msg += f"Bear Score: {debate_report.bear_score}/10\n"
            user_msg += f"Bear Thesis: {debate_report.bear_thesis}\n\n"
            user_msg += f"Net Conviction: {debate_report.net_conviction}\n\n"

        user_msg += "=== PORTFOLIO STATE ===\n"

        # Include pre-computed quant engine signals
        if quant_signals:
            user_msg += "=== PRE-COMPUTED QUANT ENGINE SIGNALS ===\n"
            qs = quant_signals.get("quant_signal", {})
            user_msg += f"Composite Score: {qs.get('composite_score', 'N/A')}/10\n"
            user_msg += f"Model Signal: {qs.get('signal', 'N/A')}\n"
            user_msg += f"Kelly Fraction: {qs.get('kelly_fraction', 0):.4f} (Half-Kelly: {qs.get('half_kelly', 0):.4f})\n"
            user_msg += f"Win Probability: {qs.get('win_probability', 0):.1%}\n"
            user_msg += f"Risk/Reward Ratio: {qs.get('risk_reward_ratio', 0):.2f}\n"
            user_msg += f"Recommended Position: {qs.get('position_size_pct', 0):.1%} ({qs.get('position_size_shares', 0)} shares)\n\n"

            rs = quant_signals.get("risk_signal", {})
            user_msg += f"Risk Approved: {rs.get('risk_approved', 'N/A')}\n"
            user_msg += f"Stop Loss: {rs.get('stop_loss_price', 'N/A')}\n"
            user_msg += f"Max Loss: {rs.get('max_loss_amount', 'N/A')} CNY\n"
            veto_reasons = rs.get("veto_reasons", [])
            if veto_reasons:
                user_msg += f"Veto Reasons: {', '.join(veto_reasons)}\n"
            user_msg += "\n"

        user_msg += "=== PORTFOLIO STATE (continued) ===\n"
        user_msg += f"Total Value: {portfolio.total_value:,.0f}\n"
        user_msg += f"Cash: {portfolio.cash:,.0f}\n"
        user_msg += f"Existing Positions: {len(portfolio.positions)}\n"
        for pos in portfolio.positions:
            user_msg += f"  - {pos.symbol} ({pos.name}): {pos.shares} shares, weight={pos.weight_pct}%, PnL={pos.unrealized_pnl_pct:+.2f}%\n"
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
            "You MUST include the 'decision_methodology' field showing the step-by-step computation."
        )

        # Call LLM (with increased retries for rate limit tolerance)
        try:
            result = self.llm.analyze(
                system_prompt=FUND_MANAGER,
                user_message=user_msg,
                max_retries=5,
            )
        except Exception as e:
            logger.warning("[FundManager] LLM call failed: %s — synthesizing from agent reports", e)
            result = self._synthesize_from_reports(agent_reports, debate_report)

        # Parse result
        if isinstance(result, str):
            try:
                text = result.strip()
                if text.startswith("```"):
                    lines = text.split("\n")
                    lines = [l for l in lines if not l.startswith("```")]
                    text = "\n".join(lines).strip()
                result = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("[FundManager] Could not parse JSON, synthesizing from reports")
                result = self._synthesize_from_reports(agent_reports, debate_report)

        if isinstance(result, dict):
            # Position size from LLM (may be 0 — use as-is, don't mask with `or`)
            pct = result.get("position_size_pct")
            if pct is None:
                pct = 0.0
            # LLM often returns percent units (e.g. 8.5 for 8.5%) — normalize to 0-1
            if pct > 1.0:
                pct = pct / 100.0
            shares_from_llm = result.get("position_size_shares")

            # Fallback: if LLM returned 0 but user holds shares, use current holding
            if pct == 0.0 and shares_from_llm in (None, 0):
                for pos in portfolio.positions:
                    if pos.symbol == symbol:
                        pct = pos.weight_pct / 100.0
                        shares_from_llm = pos.shares
                        break

            # Calculate shares from pct if LLM didn't provide them
            if not shares_from_llm and pct > 0:
                position_value = portfolio.total_value * pct
                shares_from_llm = int(position_value / (snapshot.current_price + 0.01)) // 100 * 100

            return FinalDecision(
                symbol=symbol,
                name=snapshot.name,
                current_price=snapshot.current_price,
                action=result.get("action") or "HOLD",
                confidence=result.get("confidence") or 0.5,
                target_price=result.get("target_price"),
                stop_loss=result.get("stop_loss"),
                position_size_pct=pct,
                position_size_shares=shares_from_llm or 0,
                fundamental_score=result.get("fundamental_score") or 5.0,
                technical_score=result.get("technical_score") or 5.0,
                sentiment_score=result.get("sentiment_score") or 5.0,
                summary=result.get("summary") or "",
                decision_methodology=result.get("decision_methodology") or "",
                bull_case=result.get("bull_case") or "",
                bear_case=result.get("bear_case") or "",
                risk_assessment=result.get("risk_assessment") or "",
                agent_reports=agent_reports,
                debate_report=debate_report,
                llm_model=getattr(self.llm, "model_label", ""),
            )

        return FinalDecision(
            symbol=symbol,
            name=snapshot.name,
            current_price=snapshot.current_price,
            summary="Decision unavailable - analysis error",
            llm_model=getattr(self.llm, "model_label", ""),
        )

    def _synthesize_from_reports(
        self,
        agent_reports: list[AgentReport],
        debate_report: DebateReport | None = None,
    ) -> dict:
        """Build a decision dict from agent reports when LLM is unavailable.

        Uses the same methodology as the LLM prompt: weighted scores,
        vote tally, bull/bear conviction, risk check.
        """
        scores = {"fundamental": 5.0, "technical": 5.0, "sentiment": 5.0}
        votes = {}  # agent_name -> signal
        risk_veto = False
        risk_reasons = []

        for r in agent_reports:
            name_lower = r.agent_name.lower()
            if "fundamental" in name_lower:
                scores["fundamental"] = r.score
                votes["Fundamental"] = r.signal
            elif "technical" in name_lower:
                scores["technical"] = r.score
                votes["Technical"] = r.signal
            elif "sentiment" in name_lower:
                scores["sentiment"] = r.score
                votes["Sentiment"] = r.signal
            elif "risk" in name_lower:
                if r.signal == "HOLD":
                    risk_veto = True
                    risk_reasons = r.risks[:3]

        # Step 2: Weighted score
        f_score = scores["fundamental"]
        t_score = scores["technical"]
        s_score = scores["sentiment"]
        weighted = f_score * 0.40 + t_score * 0.30 + s_score * 0.30

        # Step 3: Vote tally
        core_signals = [votes.get("Fundamental", "HOLD"), votes.get("Technical", "HOLD"), votes.get("Sentiment", "HOLD")]
        buy_count = core_signals.count("BUY")
        sell_count = core_signals.count("SELL")

        # Step 4: Bull/Bear
        bull_score = debate_report.bull_score if debate_report else 5.0
        bear_score = debate_report.bear_score if debate_report else 5.0
        net_conviction = (bull_score - bear_score) / 10.0

        # Step 5 & 6: Decision
        if risk_veto:
            action = "HOLD"
            reason = "Risk Manager VETO"
        elif weighted >= 7.5 and buy_count >= 2:
            action = "BUY"
            reason = f"weighted_score={weighted:.1f}>=7.5, {buy_count} BUY votes, risk approved"
        elif weighted <= 3.5 and sell_count >= 2:
            action = "SELL"
            reason = f"weighted_score={weighted:.1f}<=3.5, {sell_count} SELL votes"
        else:
            action = "HOLD"
            reason = f"weighted_score={weighted:.1f}, mixed signals"

        # Step 7: Position sizing — use current holding if exists
        position_pct = 0.0
        position_shares = 0
        try:
            portfolio = self.data.get_portfolio_state()
            symbol = agent_reports[0].symbol if agent_reports else ""
            for pos in portfolio.positions:
                if pos.symbol == symbol:
                    position_pct = pos.weight_pct / 100.0
                    position_shares = pos.shares
                    break
            if position_pct == 0.0 and action == "BUY":
                position_pct = 0.05
                position_shares = int(portfolio.total_value * 0.05 / 20) // 100 * 100
        except Exception:
            pass

        methodology = (
            f"Step 1 - Score Extraction: Fundamental={f_score}/10, Technical={t_score}/10, Sentiment={s_score}/10\n"
            f"Step 2 - Weighted Score: {f_score}×0.40 + {t_score}×0.30 + {s_score}×0.30 = {weighted:.2f}/10\n"
            f"Step 3 - Vote Tally: Fundamental={votes.get('Fundamental','N/A')}, Technical={votes.get('Technical','N/A')}, "
            f"Sentiment={votes.get('Sentiment','N/A')} → BUY:{buy_count} SELL:{sell_count} HOLD:{3-buy_count-sell_count}\n"
            f"Step 4 - Bull/Bear: Bull={bull_score}/10 vs Bear={bear_score}/10, Net Conviction={net_conviction:+.2f}\n"
            f"Step 5 - Risk Check: {'VETO — ' + ', '.join(risk_reasons) if risk_veto else 'Approved'}\n"
            f"Step 6 - Final Decision: {action} ({reason})\n"
            f"Step 7 - Position: {position_pct:.1%} ({position_shares} shares)\n"
            f"[Auto-synthesized — LLM unavailable]"
        )

        avg_confidence = sum(r.confidence for r in agent_reports) / max(len(agent_reports), 1)

        return {
            "action": action,
            "confidence": round(avg_confidence, 2),
            "fundamental_score": f_score,
            "technical_score": t_score,
            "sentiment_score": s_score,
            "position_size_pct": position_pct,
            "position_size_shares": position_shares,
            "decision_methodology": methodology,
            "summary": f"Weighted score: {weighted:.2f}/10. {reason}. "
                       + (f"Bull/Bear conviction: {net_conviction:+.2f}. " if debate_report else ""),
            "bull_case": debate_report.bull_thesis[:500] if debate_report else "",
            "bear_case": debate_report.bear_thesis[:500] if debate_report else "",
            "risk_assessment": f"VETO: {', '.join(risk_reasons)}" if risk_veto else "Within limits",
        }
