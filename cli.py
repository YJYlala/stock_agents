"""CLI interface for the Stock Agents system."""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Allow running as `python cli.py` directly (adds GenAI/ to sys.path so
# `stock_agents.*` imports resolve regardless of how the file is launched).
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.rule import Rule
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
            pnl_val = p.unrealized_pnl or 0
            color = "green" if pnl_val >= 0 else "red"
            table.add_row(
                p.symbol, p.name[:8], str(p.shares),
                f"{p.avg_cost:.3f}" if p.avg_cost is not None else "-",
                f"{p.current_price:.3f}" if p.current_price is not None else "-",
                f"{p.market_value:,.2f}" if p.market_value is not None else "-",
                f"[{color}]{pnl_val:+,.2f}[/]",
                f"[{color}]{(p.unrealized_pnl_pct or 0):+.2f}%[/]",
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


def cmd_report_and_notify(args, settings):
    """Run watchlist analysis, save reports, and send notifications."""
    from stock_agents.data.trading_calendar import is_trading_day
    from stock_agents.output.notify import send_all, build_report_email_html
    from stock_agents.output.report_generator import generate_report

    logger = logging.getLogger(__name__)

    # Holiday check
    if settings.schedule.skip_holidays and not args.force:
        if not is_trading_day():
            console.print("[yellow]今天不是交易日，跳过分析。[/] (use --force to override)")
            return

    # Merge held stocks into watchlist
    csv_path = _get_csv_path(settings)
    held = get_held_symbols(csv_path)
    if held:
        merged = list(dict.fromkeys(settings.watchlist + held))
        settings.watchlist = merged
    console.print(f"[dim]Watchlist: {', '.join(settings.watchlist)} ({len(settings.watchlist)} stocks)[/]")

    # Run analysis
    orchestrator = TradingOrchestrator(settings)
    decisions = orchestrator.analyze_watchlist()

    # Collect markdown reports and save files
    compliance = ComplianceLogger(settings.log_dir)
    all_reports_md = []
    saved_paths = []

    for decision in decisions:
        print_decision(decision)
        compliance.log_decision(decision)

        md_report = generate_report(decision)
        all_reports_md.append(md_report)

        if settings.output.save_to_file:
            path = save_report(decision, settings.report_dir)
            saved_paths.append(path)

    if saved_paths:
        console.print(f"[dim]Reports saved to: {settings.report_dir}[/]")

    # Build notification content
    today_str = datetime.now().strftime("%Y-%m-%d")
    subject = f"📊 Stock Agents 每日分析报告 — {today_str}"

    # Build summary line
    symbols_summary = ", ".join(
        f"{d.symbol}({d.action})" for d in decisions if d.action
    )
    body_markdown = f"# 盘前分析报告 {today_str}\n\n"
    body_markdown += f"**分析标的:** {symbols_summary}\n\n---\n\n"
    body_markdown += "\n\n---\n\n".join(all_reports_md)

    # Build styled HTML email from individual reports
    body_html = build_report_email_html(
        title=f"📊 Stock Agents 每日分析报告",
        subtitle=f"{today_str} 盘前分析 | {symbols_summary}",
        reports_markdown=all_reports_md,
    )

    # Send notifications
    notification_cfg = settings.schedule.notification
    results = send_all(subject, body_markdown, body_html, notification_cfg)

    if results:
        for channel, ok in results.items():
            status = "[green]✓[/]" if ok else "[red]✗[/]"
            console.print(f"  {channel}: {status}")
    else:
        console.print("[dim]No notification channels enabled — reports saved locally only[/]")

    # Summary
    total = len(decisions)
    buy_count = sum(1 for d in decisions if d.action and "买入" in d.action)
    sell_count = sum(1 for d in decisions if d.action and "卖出" in d.action)
    console.print(f"\n[bold]分析完成: {total}只股票, {buy_count}个买入信号, {sell_count}个卖出信号[/]")


def cmd_copilot_login(args, settings):
    """Authenticate with GitHub Copilot via OAuth device code flow."""
    from genai_common.llm.github_models_client import (
        copilot_device_code_login, _resolve_github_token,
        fetch_copilot_model_catalog, _is_classic_pat,
    )

    # Check if already authenticated AND can access Copilot API
    token, source = _resolve_github_token()
    if token and not _is_classic_pat(token):
        catalog = fetch_copilot_model_catalog(token)
        if catalog:
            console.print(f"[green]✓ Already authenticated with Copilot access[/] (token from {source})")
            console.print(f"  {len(catalog)} models available")
            console.print("[dim]Use copilot-models to see the full list[/]")
            return
        else:
            console.print(f"[yellow]Found token from {source}, but cannot access Copilot API.[/]")
            console.print("[dim]Starting Copilot-specific OAuth login...[/]\n")

    console.print("[bold]GitHub Copilot OAuth Login[/]")
    console.print("This will open your browser for GitHub authentication.")
    console.print("Your Copilot Pro subscription grants access to all models.")
    console.print()

    token = copilot_device_code_login()
    if token:
        # Verify the new token actually works for Copilot
        catalog = fetch_copilot_model_catalog(token)
        if catalog:
            console.print(f"\n[green]✓ Authentication successful![/]")
            console.print(f"  Token cached at: ~/.stock-agents/copilot_token.json")
            console.print(f"  {len(catalog)} models available")
            console.print("\n[dim]Run `python -m stock_agents copilot-models` to see available models[/]")
        else:
            console.print(f"\n[yellow]⚠ Token obtained but Copilot API returned no models.[/]")
            console.print("  Your account may not have Copilot Pro enabled.")
    else:
        console.print("\n[red]✗ Authentication failed[/]")
        console.print("  Try: `gh auth login` if you have the GitHub CLI installed")


def cmd_copilot_models(args, settings):
    """List models available under your GitHub Copilot Pro subscription."""
    from genai_common.llm.github_models_client import list_copilot_models

    console.print("[dim]Fetching model catalog from Copilot API...[/]")
    models = list_copilot_models()

    if not models:
        console.print("[yellow]Could not fetch model catalog.[/]")
        console.print("  Make sure you're authenticated:")
        console.print("  → python -m stock_agents copilot-login")
        console.print("  → or set COPILOT_GITHUB_TOKEN / GH_TOKEN env var")
        return

    table = Table(title=f"Available Copilot Models ({len(models)})", show_header=True)
    table.add_column("Model ID", style="cyan")
    for mid in sorted(models):
        table.add_row(mid)
    console.print(table)
    console.print(f"\n[dim]Use any of these in config.yaml → llm.model[/]")


def cmd_debug(args, settings) -> None:
    """Step-by-step pipeline debugger — no LLM calls by default."""
    import json as _json
    from stock_agents.data.data_manager import DataManager
    from stock_agents.orchestrator import TradingOrchestrator

    symbol = args.symbol
    phase = args.phase
    agent_name = getattr(args, "agent", None)

    console.print(Rule(f"[bold cyan]DEBUG: {symbol}  phase={phase}[/]"))

    # ── data ────────────────────────────────────────────────────────────────
    if phase in ("data", "all"):
        console.print(Rule("[yellow]Phase 1 — Raw Data[/]"))
        data = DataManager(settings)

        snap = data.get_stock_snapshot(symbol)
        t = Table(title=f"StockSnapshot — {snap.name} ({symbol})", show_header=True)
        t.add_column("Field", style="cyan"); t.add_column("Value", justify="right")
        for k, v in snap.model_dump().items():
            if k != "history":
                t.add_row(k, str(v))
        console.print(t)

        fin = data.get_financial_data(symbol)
        t2 = Table(title="FinancialData", show_header=True)
        t2.add_column("Field", style="cyan"); t2.add_column("Value", justify="right")
        for k, v in fin.model_dump().items():
            t2.add_row(k, str(v)[:80])
        console.print(t2)

        ind = data.get_technical_indicators(symbol)
        t3 = Table(title="TechnicalIndicators", show_header=True)
        t3.add_column("Field", style="cyan"); t3.add_column("Value", justify="right")
        for k, v in ind.model_dump().items():
            t3.add_row(k, str(v)[:80])
        console.print(t3)

        news = data.get_news(symbol)
        console.print(Panel(
            "\n".join(f"  [{n.get('date','')}] {n.get('title','')}" for n in news[:5]),
            title=f"News (latest 5 of {len(news)})",
        ))

        portfolio = data.get_portfolio_state()
        t4 = Table(title="Portfolio State", show_header=True)
        t4.add_column("Field", style="cyan"); t4.add_column("Value", justify="right")
        t4.add_row("total_value", f"{portfolio.total_value:,.2f}")
        t4.add_row("cash", f"{portfolio.cash:,.2f}")
        t4.add_row("positions", str(len(portfolio.positions)))
        for pos in portfolio.positions:
            t4.add_row(f"  {pos.symbol}", f"{pos.shares} shares @ {pos.avg_cost:.2f}")
        console.print(t4)

    # ── quant ────────────────────────────────────────────────────────────────
    if phase in ("quant", "all"):
        console.print(Rule("[yellow]Phase 0 — Quant Engine[/]"))
        orch = TradingOrchestrator(settings)
        signals = orch._run_quant_engine(symbol)
        for section, vals in signals.items():
            if isinstance(vals, dict):
                t = Table(title=section, show_header=True, show_lines=False)
                t.add_column("Key", style="cyan"); t.add_column("Value", justify="right")
                for k, v in vals.items():
                    if k == "signal":
                        color = "green" if v == "BUY" else "red" if v == "SELL" else "yellow"
                        t.add_row(k, f"[{color}]{v}[/]")
                    else:
                        t.add_row(k, str(v)[:80])
                console.print(t)

    # ── prompt ───────────────────────────────────────────────────────────────
    if phase in ("prompt", "all"):
        console.print(Rule("[yellow]Phase 2 — Agent Prompts (no LLM call)[/]"))
        from stock_agents.agents.fundamental_analyst import FundamentalAnalyst
        from stock_agents.agents.technical_analyst import TechnicalAnalyst
        from stock_agents.agents.sentiment_analyst import SentimentAnalyst
        from stock_agents.agents.research_bull import BullResearcher
        from stock_agents.agents.research_bear import BearResearcher
        from stock_agents.agents.quant_trader import QuantTrader
        from stock_agents.agents.risk_manager import RiskManager

        data = DataManager(settings)
        orch = TradingOrchestrator(settings)
        quant_signals = orch._run_quant_engine(symbol)
        ctx = {"portfolio": data.get_portfolio_state().model_dump(), "quant_signals": quant_signals}

        class _MockLLM:
            model_label = "mock (debug)"
            def analyze(self, *a, **kw): return {}

        agent_map = {
            "fundamental": FundamentalAnalyst(_MockLLM(), data),
            "technical": TechnicalAnalyst(_MockLLM(), data),
            "sentiment": SentimentAnalyst(_MockLLM(), data),
            "bull": BullResearcher(_MockLLM(), data),
            "bear": BearResearcher(_MockLLM(), data),
            "quant": QuantTrader(_MockLLM(), data),
            "risk": RiskManager(_MockLLM(), data),
        }
        target = {agent_name: agent_map[agent_name]} if agent_name and agent_name in agent_map else agent_map

        for name, agent in target.items():
            sys_prompt = agent.get_system_prompt()
            gathered = agent.gather_data(symbol, ctx)
            user_msg = f"Analyze stock: {symbol}\n\nData:\n{_json.dumps(gathered, ensure_ascii=False, default=str, indent=2)}"
            console.print(Rule(f"[bold]{name}[/] — system prompt ({len(sys_prompt)} chars)"))
            console.print(Panel(sys_prompt[:1200] + ("…" if len(sys_prompt) > 1200 else ""), title="System Prompt", border_style="dim"))
            console.print(Rule(f"[bold]{name}[/] — user message ({len(user_msg)} chars)"))
            console.print(Panel(user_msg[:2000] + ("…" if len(user_msg) > 2000 else ""), title="User Message", border_style="dim"))

    # ── agent ────────────────────────────────────────────────────────────────
    if phase == "agent":
        if not agent_name:
            console.print("[red]--agent is required for --phase agent[/]"); return
        console.print(Rule(f"[yellow]Single Agent Run — {agent_name} (real LLM call)[/]"))
        from stock_agents.agents.fundamental_analyst import FundamentalAnalyst
        from stock_agents.agents.technical_analyst import TechnicalAnalyst
        from stock_agents.agents.sentiment_analyst import SentimentAnalyst
        from stock_agents.agents.research_bull import BullResearcher
        from stock_agents.agents.research_bear import BearResearcher
        from stock_agents.agents.quant_trader import QuantTrader
        from stock_agents.agents.risk_manager import RiskManager

        data = DataManager(settings)
        orch = TradingOrchestrator(settings)
        quant_signals = orch._run_quant_engine(symbol)
        ctx = {"portfolio": data.get_portfolio_state().model_dump(), "quant_signals": quant_signals}
        llm = TradingOrchestrator._build_llm(settings, settings.llm.model)

        agent_cls_map = {
            "fundamental": FundamentalAnalyst, "technical": TechnicalAnalyst,
            "sentiment": SentimentAnalyst, "bull": BullResearcher,
            "bear": BearResearcher, "quant": QuantTrader, "risk": RiskManager,
        }
        cls = agent_cls_map.get(agent_name)
        if not cls:
            console.print(f"[red]Unknown agent: {agent_name}[/]"); return

        agent = cls(llm, data)
        console.print(f"[dim]Running {agent.name}...[/]")
        report = agent.analyze(symbol, ctx)
        t = Table(title=f"{agent.name} Report", show_header=True)
        t.add_column("Field", style="cyan"); t.add_column("Value")
        sig_color = "green" if report.signal == "BUY" else "red" if report.signal == "SELL" else "yellow"
        t.add_row("signal", f"[{sig_color}]{report.signal}[/]")
        t.add_row("score", f"{report.score:.1f}/10")
        t.add_row("confidence", f"{report.confidence:.0%}")
        t.add_row("key_factors", "\n".join(f"• {f}" for f in report.key_factors))
        t.add_row("risks", "\n".join(f"• {r}" for r in report.risks))
        console.print(t)
        console.print(Panel(report.reasoning, title="Reasoning", border_style="blue"))

    # ── full ─────────────────────────────────────────────────────────────────
    if phase == "full":
        console.print(Rule("[yellow]Full Pipeline (verbose, real LLM calls)[/]"))
        import asyncio
        orch = TradingOrchestrator(settings)
        decision = asyncio.run(orch.analyze_stock_async(symbol))
        from stock_agents.output.formatters import print_decision
        print_decision(decision)
        console.print(Panel(
            _json.dumps({
                "action": decision.action, "confidence": decision.confidence,
                "position_size_pct": f"{decision.position_size_pct:.1%}",
                "position_size_shares": decision.position_size_shares,
                "target_price": decision.target_price, "stop_loss": decision.stop_loss,
                "llm_model": decision.llm_model,
            }, indent=2, ensure_ascii=False),
            title="Decision JSON", border_style="green",
        ))


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
    p_analyze.add_argument("symbol", default="600519", help="Stock code (e.g., 600519)")
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

    # schedule (Windows)
    p_sched = sub.add_parser("schedule", help="Schedule daily premarket analysis (Windows)")
    p_sched.add_argument("action", choices=["install", "remove", "status"])
    p_sched.add_argument("--time", default="09:00", help="Run time HH:MM (default: 09:00)")

    # report-and-notify (cross-platform, used by GitHub Actions / cron)
    p_report = sub.add_parser(
        "report-and-notify",
        help="Run watchlist analysis + save reports + send notifications",
    )
    p_report.add_argument(
        "--force", action="store_true",
        help="Run even if today is not a trading day",
    )

    # debug
    p_debug = sub.add_parser(
        "debug",
        help="Step-by-step pipeline debugger (no LLM by default)",
    )
    p_debug.add_argument("symbol", help="Stock code (e.g., 600711)")
    p_debug.add_argument(
        "--phase",
        choices=["data", "quant", "prompt", "agent", "full", "all"],
        default="all",
        help="data/quant/prompt=no LLM  agent/full=real LLM  all=data+quant+prompt (default)",
    )
    p_debug.add_argument(
        "--agent",
        choices=["fundamental", "technical", "sentiment", "bull", "bear", "quant", "risk"],
        default=None,
        help="Filter to one agent (for --phase prompt or agent)",
    )

    # copilot-login
    sub.add_parser(
        "copilot-login",
        help="Authenticate with GitHub Copilot via OAuth (browser-based)",
    )

    # copilot-models
    sub.add_parser(
        "copilot-models",
        help="List models available under your Copilot Pro subscription",
    )

    # When run directly from VSCode with no args, default to: debug 600711 --phase all
    if len(sys.argv) == 1:
        # sys.argv += ["debug", "600711", "--phase", "all"]
        sys.argv += ["debug", "600711", "--phase", "agent", "--agent", "fundamental"]

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
        "report-and-notify": cmd_report_and_notify,
        "debug": cmd_debug,
        "copilot-login": cmd_copilot_login,
        "copilot-models": cmd_copilot_models,
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