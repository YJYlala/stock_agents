"""Copilot-style premarket plan rendering."""

from datetime import datetime

from stock_agents.models.signals import FinalDecision


def render_copilot_plan(decisions: list[FinalDecision]) -> str:
    """Generate a concise pre-trading-day action plan."""
    buys = sorted([d for d in decisions if d.action == "BUY"], key=lambda x: x.confidence, reverse=True)
    sells = sorted([d for d in decisions if d.action == "SELL"], key=lambda x: x.confidence, reverse=True)
    holds = sorted([d for d in decisions if d.action == "HOLD"], key=lambda x: x.confidence, reverse=True)

    lines = [
        f"# Copilot Trading Plan ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
        "",
        "## 1. Prioritized actions",
    ]
    if buys:
        lines.append("- Focus BUY candidates:")
        for d in buys[:5]:
            lines.append(
                f"  - {d.symbol} {d.name} | confidence {d.confidence:.0%} | target pos {d.position_size_pct:.1%} | shares {d.position_size_shares}"
            )
    if sells:
        lines.append("- Reduce/exit candidates:")
        for d in sells[:5]:
            lines.append(f"  - {d.symbol} {d.name} | confidence {d.confidence:.0%}")
    if not buys and not sells:
        lines.append("- No high-conviction trade actions. Keep risk controlled and wait for better setups.")

    lines.append("")
    lines.append("## 2. Watchlist monitoring focus")
    if holds:
        for d in holds[:5]:
            lines.append(f"- {d.symbol} {d.name}: HOLD ({d.confidence:.0%}), monitor breakout/earnings/news changes.")
    else:
        lines.append("- All names currently have actionable direction.")

    lines.append("")
    lines.append("## 3. Risk checks before open")
    lines.append("- Confirm total planned positions remain within configured max single-position and drawdown limits.")
    lines.append("- Re-check overnight macro/news headlines for symbols with BUY/SELL actions.")
    lines.append("- Use limit orders around target zones; avoid chasing opening volatility.")
    return "\n".join(lines)
