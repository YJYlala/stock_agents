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
from stock_agents.output.formatters import (
    print_decision, print_watchlist_summary,
    print_multi_horizon_decision, print_multi_horizon_watchlist,
)
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
    horizon = getattr(args, "horizon", None)

    if horizon == "all" or horizon is None and getattr(args, "multi", False):
        # Multi-horizon mode
        from stock_agents.multi_horizon import MultiHorizonOrchestrator
        orchestrator = MultiHorizonOrchestrator(settings)
        result = orchestrator.analyze_stock(args.symbol)

        print_multi_horizon_decision(result)

        compliance = ComplianceLogger(settings.log_dir)
        # Log each horizon's decision
        for d in [result.short_term, result.mid_term, result.long_term]:
            if d:
                compliance.log_decision(d)
        if settings.output.save_to_file:
            for d in [result.short_term, result.mid_term, result.long_term]:
                if d:
                    path = save_report(d, settings.report_dir)
            console.print(f"[dim]Reports saved to: {settings.report_dir}[/]")
    elif horizon and horizon != "all":
        # Single horizon mode
        from stock_agents.config.horizons import Horizon
        from stock_agents.multi_horizon import MultiHorizonOrchestrator
        h = Horizon(horizon)
        orchestrator = MultiHorizonOrchestrator(settings, horizons=[h])
        result = orchestrator.analyze_stock(args.symbol)
        # Show just that horizon's decision
        decision = getattr(result, f"{horizon}_term", None)
        if decision:
            print_decision(decision)
            compliance = ComplianceLogger(settings.log_dir)
            compliance.log_decision(decision)
            if settings.output.save_to_file:
                path = save_report(decision, settings.report_dir)
                console.print(f"[dim]Report saved to: {path}[/]")
    else:
        # Default: original single-team analysis (backward compatible)
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

    horizon = getattr(args, "horizon", None)

    if horizon == "all":
        # Multi-horizon watchlist
        from stock_agents.multi_horizon import MultiHorizonOrchestrator
        orchestrator = MultiHorizonOrchestrator(settings)
        results = orchestrator.analyze_watchlist()

        print_multi_horizon_watchlist(results)

        compliance = ComplianceLogger(settings.log_dir)
        for result in results:
            print_multi_horizon_decision(result)
            for d in [result.short_term, result.mid_term, result.long_term]:
                if d:
                    compliance.log_decision(d)
                    if settings.output.save_to_file:
                        save_report(d, settings.report_dir)
        console.print(f"[dim]Reports saved to: {settings.report_dir}[/]")
    else:
        # Default: single-team analysis
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

    if args.trade_action in ("buy", "sell"):
        # Load portfolio state after the trade for market_value + cash_remaining
        # First record without the new fields to update the CSV...
        action = args.trade_action
        symbol = args.symbol.strip()
        shares = args.shares
        price = args.price
        commission = getattr(args, "commission", 0.0)
        note = getattr(args, "note", "")

        # Compute post-trade portfolio figures
        state_before = load_portfolio(csv_path)
        trade_value = shares * price + commission
        if action == "buy":
            cash_after = state_before.cash - trade_value
        else:
            cash_after = state_before.cash + (shares * price) - commission

        # Calculate market value of this position after the trade
        pos_shares = 0
        pos_name = ""
        avg_cost = price
        for pos in state_before.positions:
            if pos.symbol == symbol:
                pos_name = pos.name
                pos_shares = pos.shares
                avg_cost = pos.avg_cost
                break

        new_shares = pos_shares + shares if action == "buy" else max(0, pos_shares - shares)
        market_value_pos = new_shares * price  # position market value at trade price

        record_trade(
            csv_path, action, symbol, pos_name or symbol,
            shares, price, commission, note,
            market_value=market_value_pos,
            cash_remaining=max(cash_after, 0),
        )

        color = "green" if action == "buy" else "red"
        console.print(
            f"[{color}]{'买入' if action == 'buy' else '卖出'} {shares:,} 股  {symbol}({pos_name or symbol})  "
            f"@ {price:.3f}  手续费 {commission:.2f}[/]"
        )
        console.print(f"  当前市值 (该股)  : CNY [bold]{market_value_pos:>12,.2f}[/]  ({new_shares:,} 股 × {price:.3f})")
        console.print(f"  剩余资金         : CNY [bold]{max(cash_after, 0):>12,.2f}[/]")

    elif args.trade_action == "history":
        import csv as csv_mod
        csv_file = Path(csv_path)
        if not csv_file.exists():
            console.print("[dim]No trades recorded yet[/]")
            return
        with open(csv_file, encoding="utf-8-sig") as f:
            header_line = f.readline()
        has_new_cols = "market_value" in header_line

        with open(csv_file, encoding="utf-8-sig") as f:
            reader = csv_mod.DictReader(f)
            table = Table(title="操作记录", show_header=True)
            table.add_column("日期", width=12)
            table.add_column("操作", width=6)
            table.add_column("代码", width=8)
            table.add_column("名称", width=10)
            table.add_column("股数", justify="right", width=8)
            table.add_column("价格", justify="right", width=8)
            table.add_column("手续费", justify="right", width=8)
            if has_new_cols:
                table.add_column("当前市值", justify="right", width=12)
                table.add_column("剩余资金", justify="right", width=12)
            table.add_column("备注")
            for row in reader:
                action = row.get("action", "")
                if action not in ("buy", "sell"):
                    continue
                color = "green" if action == "buy" else "red"
                label = "买入" if action == "buy" else "卖出"
                cols = [
                    row.get("date", ""),
                    f"[{color}]{label}[/]",
                    row.get("symbol", ""),
                    row.get("name", ""),
                    row.get("shares", ""),
                    row.get("price", ""),
                    row.get("commission", ""),
                ]
                if has_new_cols:
                    mv = float(row.get("market_value") or 0)
                    cr = float(row.get("cash_remaining") or 0)
                    cols += [
                        f"[bold]{mv:,.2f}[/]" if mv else "-",
                        f"[bold]{cr:,.2f}[/]" if cr else "-",
                    ]
                cols.append(row.get("note", ""))
                table.add_row(*cols)
        console.print(table)

    # Show updated portfolio summary
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
    p_analyze.add_argument(
        "--horizon", choices=["short", "mid", "long", "all"],
        default=None,
        help="Investment horizon: short (≤1mo), mid (1-6mo), long (6mo+), all (三周期)",
    )

    # watchlist
    p_wl = sub.add_parser("watchlist", help="Analyze all stocks in watchlist")
    p_wl.add_argument(
        "--horizon", choices=["short", "mid", "long", "all"],
        default=None,
        help="Investment horizon: short, mid, long, or all (三周期)",
    )

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