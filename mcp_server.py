"""MCP server exposing stock_agents analysis tools."""

from __future__ import annotations

from stock_agents.config.settings import load_settings
from stock_agents.data.futu_client import FutuClient
from stock_agents.data.ths_client import THSClient
from stock_agents.orchestrator import TradingOrchestrator
from stock_agents.output.copilot_plan import render_copilot_plan
from stock_agents.output.report_generator import generate_report

def _build_account_client(settings, provider_override: str | None = None):
    provider = provider_override or settings.account.provider
    if provider == "futu":
        client = FutuClient(settings.futu.host, settings.futu.port)
        return client if client.connect() else None
    if provider == "ths":
        client = THSClient(
            positions_file=settings.ths.positions_file,
            cash_file=settings.ths.cash_file,
            watchlist_file=settings.ths.watchlist_file,
            total_capital=settings.risk.total_capital,
        )
        return client if client.connect() else None
    return None


def _sync_ths_watchlist(settings, provider: str, account_client) -> None:
    if provider != "ths":
        return
    if not settings.ths.sync_watchlist:
        return
    if not account_client or not hasattr(account_client, "get_watchlist_symbols"):
        return
    symbols = account_client.get_watchlist_symbols()
    if symbols:
        settings.watchlist = symbols


def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise RuntimeError("mcp package is required. Install with: pip install mcp") from e

    mcp = FastMCP("stock-agents")

    @mcp.tool()
    def generate_watchlist_plan(config_path: str | None = None, account_provider: str | None = None) -> str:
        """Run full watchlist analysis and return a premarket plan."""
        settings = load_settings(config_path)
        provider = account_provider or settings.account.provider
        account_client = _build_account_client(settings, provider_override=account_provider)
        try:
            _sync_ths_watchlist(settings, provider, account_client)
            orchestrator = TradingOrchestrator(settings, account_client=account_client)
            decisions = orchestrator.analyze_watchlist()
            return render_copilot_plan(decisions)
        finally:
            if account_client:
                account_client.disconnect()

    @mcp.tool()
    def analyze_symbol(symbol: str, config_path: str | None = None, account_provider: str | None = None) -> str:
        """Analyze a single symbol and return a markdown report."""
        settings = load_settings(config_path)
        account_client = _build_account_client(settings, provider_override=account_provider)
        try:
            orchestrator = TradingOrchestrator(settings, account_client=account_client)
            decision = orchestrator.analyze_stock(symbol)
            return generate_report(decision)
        finally:
            if account_client:
                account_client.disconnect()

    mcp.run()


if __name__ == "__main__":
    main()
