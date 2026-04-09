"""CLI interface for the Stock Agents system."""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from stock_agents.config.settings import load_settings
from stock_agents.compliance.logger import ComplianceLogger
from stock_agents.data.csv_portfolio import load_portfolio, record_trade, get_held_symbols
from stock_agents.orchestrator import TradingOrchestrator
from stock_agents.output.copilot_plan import render_copilot_plan
from stock_agents.output.formatters import print_decision, print_watchlist_summary
from stock_agents.output.report_generator import save_report

console = Console()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("akshare").setLevel(logging.WARNING)


def _get_csv_path(settings) -> str:
    """Get portfolio CSV path."""
    return str(settings.base_dir / "portfolio.csv")


def cmd_analyze(args, settings):
    """Analyze a single stock."""
    orchestrator = TradingOrchestrator(settings)
    decision = orchestrator.analyze_stock(args.symbol)

    print_decision(decision)

    compliance = ComplianceLogger(settings.log_dir)
    compliance.log_decision(decision)

    if settings.output.save_to_file:
        path = save_report(decision, settings.report_dir)
        console.print(f"[dim]Report saved to: {path}[/]")


def cmd_watchlist(args, settings):
    """Analyze all stocks in watchlist."""
    # Merge config watchlist with held stocks from portfolio.csv
    csv_path = _get_csv_path(settings)
    held = get_held_symbols(csv_path)
    if held:
        merged = list(dict.fromkeys(settings.watchlist + held))
        settings.watchlist = merged
    console.print(f"[dim]Watchlist: {', '.join(settings.watchlist)} ({len(settings.watchlist)} stocks)[/]")

    orchestrator = TradingOrchestrator(settings)
    decisions = orchestrator.analyze_watchlist()

    print_watchlist_summary(decisions)

    compliance = ComplianceLogger(settings.log_dir)
    for decision in decisions:
        print_decision(decision)
        compliance.log_decision(decision)
        if settings.output.save_to_file:
            save_report(decision, settings.report_dir)

    console.print(f"[dim]Reports saved to: {settings.report_dir}[/]")


def cmd_portfolio(args, settings):
    """Show current portfolio from CSV."""
    csv_path = _get_csv_path(settings)
    state = load_portfolio(csv_path)

    console.print(f"\n[bold]Portfolio Summary[/] (from portfolio.csv)\n")
    console.print(f"  Cash:       CNY {state.cash:>12,.2f}")
    console.print(f"  Holdings:   CNY {sum(p.market_value for p in state.positions):>12,.2f}")
    console.print(f"  Total:      CNY {state.total_value:>12,.2f}")
    console.print(f"  PnL:        CNY {state.total_unrealized_pnl:>+12,.2f}")

    if state.positions:
        table = Table(show_header=True)
        table.add_column("Symbol", width=8)
        table.add_column("Name", width=10)
        table.add_column("Shares", justify="right", width=8)
        table.add_column("Avg Cost", justify="right", width=10)
        table.add_column("Cur Price", justify="right", width=10)
        table.add_column("Mkt Value", justify="right", width=12)
        table.add_column("PnL", justify="right", width=10)
        table.add_column("PnL%", justify="right", width=8)
        table.add_column("Weight", justify="right", width=8)
        for p in state.positions:
            color = "green" if p.unrealized_pnl >= 0 else "red"
            table.add_row(
                p.symbol, p.name[:8], str(p.shares),
                f"{p.avg_cost:.3f}", f"{p.current_price:.3f}",
                f"{p.market_value:,.2f}",
                f"[{color}]{p.unrealized_pnl:+,.2f}[/]",
                f"[{color}]{p.unrealized_pnl_pct:+.2f}%[/]",
                f"{p.weight_pct:.1f}%",
            )
        console.print(table)
    console.print()


def cmd_trade(args, settings):
    """Record a trade."""
    csv_path = _get_csv_path(settings)

    if args.trade_action == "buy":
        record_trade(csv_path, "buy", args.symbol, "", args.shares, args.price, args.commission, args.note)
        console.print(f"[green]Recorded: BUY {args.shares} x {args.symbol} @ {args.price:.2f}[/]")
    elif args.trade_action == "sell":
        record_trade(csv_path, "sell", args.symbol, "", args.shares, args.price, args.commission, args.note)
        console.print(f"[red]Recorded: SELL {args.shares} x {args.symbol} @ {args.price:.2f}[/]")
    elif args.trade_action == "history":
        import csv as csv_mod
        csv_file = Path(csv_path)
        if not csv_file.exists():
            console.print("[dim]No trades recorded yet[/]")
            return
        with open(csv_file, encoding="utf-8-sig") as f:
            reader = csv_mod.DictReader(f)
            table = Table(title="Trade History", show_header=True)
            table.add_column("Date")
            table.add_column("Action", width=8)
            table.add_column("Symbol", width=8)
            table.add_column("Name", width=10)
            table.add_column("Shares", justify="right")
            table.add_column("Price", justify="right")
            table.add_column("Note")
            for row in reader:
                action = row.get("action", "")
                color = "green" if action == "buy" else "red" if action == "sell" else "dim"
                table.add_row(
                    row.get("date", ""), f"[{color}]{action}[/]",
                    row.get("symbol", ""), row.get("name", ""),
                    row.get("shares", ""), row.get("price", ""), row.get("note", ""),
                )
            console.print(table)

    # Show updated portfolio
    cmd_portfolio(args, settings)


def cmd_copilot_plan(args, settings):
    """Generate a premarket Copilot-style watchlist plan."""
    csv_path = _get_csv_path(settings)
    held = get_held_symbols(csv_path)
    if held:
        merged = list(dict.fromkeys(settings.watchlist + held))
        settings.watchlist = merged

    orchestrator = TradingOrchestrator(settings)
    decisions = orchestrator.analyze_watchlist()
    print_watchlist_summary(decisions)

    plan = render_copilot_plan(decisions)
    console.print(Panel(plan, title="Copilot Pre-market Plan", border_style="blue"))

    if args.save_plan:
        settings.report_dir.mkdir(parents=True, exist_ok=True)
        output_path = settings.report_dir / f"copilot_plan_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        output_path.write_text(plan + "\n", encoding="utf-8")
        console.print(f"[dim]Plan saved to: {output_path}[/]")


def cmd_config(args, settings):
    """Show current configuration."""
    console.print("\n[bold]Current Configuration[/]\n")
    console.print(f"LLM Provider: {settings.llm.provider}")
    console.print(f"LLM Model: {settings.llm.model} (via GitHub Models)")
    console.print(f"LLM Final: {settings.llm.model_final}")
    console.print(f"LLM Endpoint: {settings.llm.endpoint}")
    console.print(f"LLM API Key Env: {settings.llm.api_key_env}")
    console.print(f"LLM Fallback: {settings.llm.fallback}")
    console.print(f"Ollama Model: {settings.ollama.model}")
    console.print(f"Ollama Endpoint: {settings.ollama.endpoint}")
    console.print(f"Watchlist: {', '.join(settings.watchlist)}")
    console.print(f"Lookback: {settings.analysis.lookback_days} days")
    console.print(f"Max Position: {settings.risk.max_single_position_pct:.0%}")
    console.print(f"Max Drawdown: {settings.risk.max_drawdown_pct:.0%}")
    console.print(f"Capital: CNY {settings.risk.total_capital:,.0f}")

    csv_path = _get_csv_path(settings)
    state = load_portfolio(csv_path)
    console.print(f"\nPortfolio CSV: {csv_path}")
    console.print(f"Portfolio Cash: CNY {state.cash:,.2f}")
    console.print(f"Portfolio Total: CNY {state.total_value:,.2f}")
    if state.positions:
        console.print(f"Holdings: {', '.join(p.symbol + '(' + p.name + ')' for p in state.positions)}")
    console.print()


def cmd_schedule(args, settings):
    """Install/remove/show Windows Task Scheduler job for daily premarket analysis."""
    import subprocess
    task_name = "StockAgentsPremarket"
    python_exe = sys.executable
    project_dir = settings.base_dir
    script = f'cd /d "{project_dir}" && "{python_exe}" -m stock_agents.cli copilot-plan --save-plan'

    if args.action == "install":
        hh, mm = args.time.split(":")
        subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"], capture_output=True)
        result = subprocess.run(
            ["schtasks", "/Create", "/TN", task_name,
             "/TR", f'cmd /c "{script}"', "/SC", "DAILY", "/ST", f"{hh}:{mm}", "/F"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            console.print(f"[green]Scheduled '{task_name}' daily at {hh}:{mm}[/]")
        else:
            console.print(f"[red]Failed: {result.stderr}[/]")

    elif args.action == "remove":
        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", task_name, "/F"], capture_output=True, text=True)
        console.print("[green]Removed[/]" if result.returncode == 0 else "[yellow]Not found[/]")

    elif args.action == "status":
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name, "/V", "/FO", "LIST"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if any(k in line for k in ["Status", "Next Run", "Last Run", "Schedule", "Start Time"]):
                    console.print(f"  {line}")
        else:
            console.print(f"[dim]No task '{task_name}' found[/]")


def main():
    parser = argparse.ArgumentParser(
        prog="stock_agents",
        description="Multi-Agent Stock Trading Advisory System (A-Shares)",
    )
    parser.add_argument("-c", "--config", help="Config file path", default=None)
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # analyze
    p_analyze = sub.add_parser("analyze", help="Analyze a single stock")
    p_analyze.add_argument("symbol", help="Stock code (e.g., 600519)")

    # watchlist
    sub.add_parser("watchlist", help="Analyze all stocks in watchlist")

    # portfolio
    sub.add_parser("portfolio", help="Show portfolio (from CSV tracker)")

    # trade
    p_trade = sub.add_parser("trade", help="Record a trade or set cash")
    trade_sub = p_trade.add_subparsers(dest="trade_action")

    p_buy = trade_sub.add_parser("buy", help="Record a buy trade")
    p_buy.add_argument("symbol", help="Stock code")
    p_buy.add_argument("shares", type=int, help="Number of shares")
    p_buy.add_argument("price", type=float, help="Price per share")
    p_buy.add_argument("--commission", type=float, default=0.0, help="Commission (default: 0)")
    p_buy.add_argument("--note", default="", help="Optional note")

    p_sell = trade_sub.add_parser("sell", help="Record a sell trade")
    p_sell.add_argument("symbol", help="Stock code")
    p_sell.add_argument("shares", type=int, help="Number of shares")
    p_sell.add_argument("price", type=float, help="Price per share")
    p_sell.add_argument("--commission", type=float, default=0.0, help="Commission (default: 0)")
    p_sell.add_argument("--note", default="", help="Optional note")

    p_cash = trade_sub.add_parser("cash", help="Set cash balance")
    p_cash.add_argument("amount", type=float, help="Cash amount in CNY")

    trade_sub.add_parser("history", help="Show trade history")

    # config
    sub.add_parser("config", help="Show current config")

    # copilot plan
    p_plan = sub.add_parser("copilot-plan", help="Generate premarket action plan")
    p_plan.add_argument("--save-plan", action="store_true", help="Save plan to reports dir")

    # schedule
    p_sched = sub.add_parser("schedule", help="Schedule daily premarket analysis (Windows)")
    p_sched.add_argument("action", choices=["install", "remove", "status"])
    p_sched.add_argument("--time", default="09:00", help="Run time HH:MM (default: 09:00)")

    args = parser.parse_args()
    setup_logging(args.verbose)
    settings = load_settings(args.config)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "analyze": cmd_analyze,
        "watchlist": cmd_watchlist,
        "portfolio": cmd_portfolio,
        "trade": cmd_trade,
        "config": cmd_config,
        "copilot-plan": cmd_copilot_plan,
        "schedule": cmd_schedule,
    }

    cmd_fn = commands.get(args.command)
    if cmd_fn:
        cmd_fn(args, settings)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
"""
 python -m stock_agents.cli analyze 600711 2>&1
"""