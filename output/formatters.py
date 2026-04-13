"""Rich console output formatters."""

import io
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from stock_agents.models.signals import FinalDecision, MultiHorizonDecision

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


def print_multi_horizon_decision(mhd: MultiHorizonDecision) -> None:
    """Print a multi-horizon decision with side-by-side comparison."""
    # Header
    consensus_color = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(
        mhd.consensus_action, "white"
    )
    console.print()
    console.print(Panel(
        f"[bold {consensus_color}]综合建议: {mhd.consensus_action}[/]  "
        f"置信度: {mhd.consensus_confidence:.0%}  |  当前价: {mhd.current_price:.2f}",
        title=f"[bold]🔬 {mhd.name} ({mhd.symbol}) — 三周期分析[/]",
        subtitle=f"{mhd.timestamp.strftime('%Y-%m-%d %H:%M')}",
        border_style=consensus_color,
    ))

    # Three-column comparison table
    table = Table(
        title="短线 vs 中线 vs 长线",
        show_header=True, header_style="bold",
        width=100,
    )
    table.add_column("指标", style="cyan", width=14)
    table.add_column("短线 (≤1月)", justify="center", width=26)
    table.add_column("中线 (1-6月)", justify="center", width=26)
    table.add_column("长线 (6月+)", justify="center", width=26)

    decisions = [mhd.short_term, mhd.mid_term, mhd.long_term]
    labels = ["短线", "中线", "长线"]

    def _cell(d: FinalDecision | None, fmt_fn) -> str:
        if d is None:
            return "[dim]—[/]"
        return fmt_fn(d)

    def _action_cell(d):
        c = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(d.action, "white")
        return f"[bold {c}]{d.action}[/] ({d.confidence:.0%})"

    def _score_cell(d, attr):
        v = getattr(d, attr, 5.0)
        c = "green" if v >= 7 else "yellow" if v >= 5 else "red"
        return f"[{c}]{v:.1f}[/]"

    def _price_cell(d, attr):
        v = getattr(d, attr, None)
        return f"{v:.2f}" if v else "-"

    def _pct_cell(d):
        return f"{d.position_size_pct:.1%}" if d.position_size_pct else "0%"

    def _shares_cell(d):
        return f"{d.position_size_shares}" if d.position_size_shares else "0"

    # Rows
    table.add_row("建议",
                  *[_cell(d, _action_cell) for d in decisions])
    table.add_row("基本面",
                  *[_cell(d, lambda d: _score_cell(d, "fundamental_score")) for d in decisions])
    table.add_row("技术面",
                  *[_cell(d, lambda d: _score_cell(d, "technical_score")) for d in decisions])
    table.add_row("情绪面",
                  *[_cell(d, lambda d: _score_cell(d, "sentiment_score")) for d in decisions])
    table.add_row("目标价",
                  *[_cell(d, lambda d: _price_cell(d, "target_price")) for d in decisions])
    table.add_row("止损价",
                  *[_cell(d, lambda d: _price_cell(d, "stop_loss")) for d in decisions])
    table.add_row("建议仓位",
                  *[_cell(d, _pct_cell) for d in decisions])
    table.add_row("建议股数",
                  *[_cell(d, _shares_cell) for d in decisions])

    console.print(table)

    # Consensus summary
    if mhd.consensus_summary:
        console.print(Panel(
            mhd.consensus_summary,
            title="[bold]三周期共识[/]",
            border_style="blue",
        ))

    # Per-horizon summaries (collapsed)
    for d, label in zip(decisions, labels):
        if d and d.summary:
            console.print(Panel(
                d.summary[:500] + ("..." if len(d.summary) > 500 else ""),
                title=f"[bold]{label}决策摘要[/]",
                border_style="dim",
            ))

    console.print()


def print_multi_horizon_watchlist(results: list[MultiHorizonDecision]) -> None:
    """Print compact watchlist summary for multi-horizon analysis."""
    table = Table(
        title="三周期投资分析总览",
        show_header=True, header_style="bold",
    )
    table.add_column("代码", style="cyan", width=8)
    table.add_column("名称", width=8)
    table.add_column("现价", justify="right", width=8)
    table.add_column("短线", justify="center", width=10)
    table.add_column("中线", justify="center", width=10)
    table.add_column("长线", justify="center", width=10)
    table.add_column("共识", justify="center", width=10)

    for mhd in results:
        def _fmt(d):
            if d is None:
                return "[dim]—[/]"
            c = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(d.action, "white")
            return f"[{c}]{d.action}[/]"

        c_color = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(
            mhd.consensus_action, "white"
        )
        table.add_row(
            mhd.symbol,
            (mhd.name or "")[:8],
            f"{mhd.current_price:.2f}" if mhd.current_price else "-",
            _fmt(mhd.short_term),
            _fmt(mhd.mid_term),
            _fmt(mhd.long_term),
            f"[bold {c_color}]{mhd.consensus_action}[/]",
        )

    console.print()
    console.print(table)
    console.print()
