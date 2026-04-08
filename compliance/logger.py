"""Compliance audit logger - logs all decisions as structured JSON."""

import json
import logging
from datetime import datetime
from pathlib import Path

from stock_agents.models.signals import FinalDecision

logger = logging.getLogger(__name__)


class ComplianceLogger:
    """Logs all trading decisions for audit compliance."""

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log_decision(self, decision: FinalDecision) -> None:
        """Append decision to daily log file."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = self.log_dir / f"{date_str}.jsonl"

        entry = {
            "timestamp": datetime.now().isoformat(),
            "symbol": decision.symbol,
            "name": decision.name,
            "action": decision.action,
            "confidence": decision.confidence,
            "fundamental_score": decision.fundamental_score,
            "technical_score": decision.technical_score,
            "sentiment_score": decision.sentiment_score,
            "position_size_pct": decision.position_size_pct,
            "position_size_shares": decision.position_size_shares,
            "target_price": decision.target_price,
            "stop_loss": decision.stop_loss,
            "summary": decision.summary[:500],
            "agent_count": len(decision.agent_reports),
            "agent_signals": {
                r.agent_name: {"signal": r.signal, "score": r.score, "confidence": r.confidence}
                for r in decision.agent_reports
            },
            "debate_net_conviction": decision.debate_report.net_conviction if decision.debate_report else None,
        }

        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            logger.info("Decision logged to %s", log_file)
        except Exception as e:
            logger.error("Failed to log decision: %s", e)
