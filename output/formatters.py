"""Rich console output formatters."""

import io
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from stock_agents.models.signals import FinalDecision

# Force UTF-8 output to avoid GBK encoding errors on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

console = Console(force_terminal=True)


def print_decision(decision: FinalDecision) -> None:
    """Print a FinalDecision to console with rich formatting."""
    action_color = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(decision.action, "white")

    # Header with price
    price_str = f"  |  当前价: {decision.current_price:.2f}" if decision.current_price else ""
    console.print()
    console.print(Panel(
        f"[bold {action_color}]{decision.action}[/] - 置信度: {decision.confidence:.0%}{price_str}",
        title=f"[bold]{decision.name} ({decision.symbol})[/]",
        subtitle=f"{decision.timestamp.strftime('%Y-%m-%d %H:%M')}",
        border_style=action_color,
    ))

    # Scores table
    scores = Table(title="多维度评分", show_header=True)
    scores.add_column("维度", style="cyan")
    scores.add_column("得分", justify="right")
    scores.add_column("评级", justify="center")

    for name, score in [
        ("基本面", decision.fundamental_score),
        ("技术面", decision.technical_score),
        ("情绪面", decision.sentiment_score),
    ]:
        bar = "#" * int(score) + "-" * (10 - int(score))
        color = "green" if score >= 7 else "yellow" if score >= 5 else "red"
        scores.add_row(name, f"[{color}]{score:.1f}/10[/]", f"[{color}]{bar}[/]")
    console.print(scores)

    # Price targets table
    price_table = Table(title="价格信息", show_header=True)
    price_table.add_column("项目", style="cyan")
    price_table.add_column("数值", justify="right")
    if decision.current_price:
        price_table.add_row("当前价格", f"{decision.current_price:.2f}")
    if decision.target_price:
        price_table.add_row("目标价格", f"[green]{decision.target_price:.2f}[/]")
        if decision.current_price:
            upside = (decision.target_price - decision.current_price) / decision.current_price * 100
            price_table.add_row("上涨空间", f"[green]{upside:+.1f}%[/]")
    if decision.stop_loss:
        price_table.add_row("止损价格", f"[red]{decision.stop_loss:.2f}[/]")
        if decision.current_price:
            downside = (decision.stop_loss - decision.current_price) / decision.current_price * 100
            price_table.add_row("下跌风险", f"[red]{downside:+.1f}%[/]")
    console.print(price_table)

    # Position table
    pos = Table(title="仓位建议", show_header=True)
    pos.add_column("项目", style="cyan")
    pos.add_column("数值", justify="right")
    pos.add_row("建议仓位", f"{decision.position_size_pct:.1%}")
    pos.add_row("建议股数", f"{decision.position_size_shares} 股 ({decision.position_size_shares // 100} 手)")
    console.print(pos)

    # Summary
    if decision.summary:
        console.print(Panel(decision.summary, title="[bold]决策摘要[/]", border_style="blue"))

    console.print()


def print_watchlist_summary(decisions: list[FinalDecision]) -> None:
    """Print summary table for all watchlist stocks."""
    table = Table(title="投资组合分析总览", show_header=True, header_style="bold")
    table.add_column("代码", style="cyan", width=8)
    table.add_column("名称", width=10)
    table.add_column("现价", justify="right", width=10)
    table.add_column("建议", justify="center", width=6)
    table.add_column("置信度", justify="right", width=8)
    table.add_column("基本面", justify="right", width=6)
    table.add_column("技术面", justify="right", width=6)
    table.add_column("情绪面", justify="right", width=6)
    table.add_column("目标价", justify="right", width=10)
    table.add_column("止损价", justify="right", width=10)

    for d in decisions:
        color = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(d.action, "white")
        table.add_row(
            d.symbol,
            d.name[:8],
            f"{d.current_price:.2f}" if d.current_price else "-",
            f"[bold {color}]{d.action}[/]",
            f"{d.confidence:.0%}",
            f"{d.fundamental_score:.1f}",
            f"{d.technical_score:.1f}",
            f"{d.sentiment_score:.1f}",
            f"{d.target_price:.2f}" if d.target_price else "-",
            f"{d.stop_loss:.2f}" if d.stop_loss else "-",
        )

    console.print()
    console.print(table)
    console.print()
