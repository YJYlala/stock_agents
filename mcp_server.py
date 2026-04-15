"""MCP server exposing stock_agents analysis tools."""


from stock_agents.config.settings import load_settings
from stock_agents.orchestrator import TradingOrchestrator
from stock_agents.output.copilot_plan import render_copilot_plan
from stock_agents.output.report_generator import generate_report


def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise RuntimeError("mcp package is required. Install with: pip install mcp") from e

    mcp = FastMCP("stock-agents")

    @mcp.tool()
    def generate_watchlist_plan(config_path: str | None = None) -> str:
        """Run full watchlist analysis and return a premarket plan."""
        settings = load_settings(config_path)
        orchestrator = TradingOrchestrator(settings)
        decisions = orchestrator.analyze_watchlist()
        return render_copilot_plan(decisions)

    @mcp.tool()
    def analyze_symbol(symbol: str, config_path: str | None = None) -> str:
        """Analyze a single symbol and return a markdown report."""
        settings = load_settings(config_path)
        orchestrator = TradingOrchestrator(settings)
        decision = orchestrator.analyze_stock(symbol)
        return generate_report(decision)

    mcp.run()


if __name__ == "__main__":
    main()
