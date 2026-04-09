# Stock Agents - Multi-Agent Stock Analysis System

A multi-agent AI system for China A-share stock analysis, powered by LLM-based analyst agents that collaborate through a structured 5-phase pipeline to produce comprehensive investment analysis reports.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                     CLI / MCP Server                     │
│                  (cli.py / mcp_server.py)                │
└─────────────┬───────────────────────────────┬───────────┘
              │                               │
              ▼                               ▼
┌──────────────────────┐    ┌──────────────────────────────┐
│    Orchestrator       │    │      Config & Settings        │
│  (orchestrator.py)    │◄───│  (config.yaml + settings.py)  │
│  5-Phase Pipeline     │    │  prompts.py (8 agent prompts) │
└──────────┬───────────┘    └──────────────────────────────┘
           │
           │  Phase 1: Data Pre-fetch
           ▼
┌──────────────────────────────────────────┐
│            Data Layer                     │
│  ┌─────────────┐  ┌──────────────────┐  │
│  │ AKShare      │  │ CSV Portfolio    │  │
│  │ (market data)│  │ (holdings/trades)│  │
│  └─────────────┘  └──────────────────┘  │
│  ┌─────────────┐  ┌──────────────────┐  │
│  │ File Cache   │  │ THS / Futu       │  │
│  │ (JSON, TTL)  │  │ (broker clients) │  │
│  └─────────────┘  └──────────────────┘  │
└──────────────────────────────────────────┘
           │
           │  Phase 2-5: Agent Analysis
           ▼
┌──────────────────────────────────────────┐
│           LLM Backends (llm/)            │
│  ┌────────────┐  ┌───────────────────┐  │
│  │ GitHub      │  │ Claude (Anthropic)│  │
│  │ Models API  │  │                   │  │
│  └────────────┘  └───────────────────┘  │
│  ┌────────────┐  ┌───────────────────┐  │
│  │ Ollama     │  │ Fallback Client   │  │
│  │ (local)    │  │ (auto-switch)     │  │
│  └────────────┘  └───────────────────┘  │
└──────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────┐
│          8 Analyst Agents                │
│                                          │
│  Phase 2: Independent Analysis           │
│  ┌──────────┐ ┌──────────┐ ┌─────────┐ │
│  │Fundamental│ │Technical │ │Sentiment│ │
│  │ Analyst   │ │ Analyst  │ │ Analyst │ │
│  │ (40%)     │ │ (30%)    │ │ (30%)   │ │
│  └──────────┘ └──────────┘ └─────────┘ │
│                                          │
│  Phase 3: Bull/Bear Debate               │
│  ┌──────────────┐  ┌──────────────┐     │
│  │Bull Researcher│  │Bear Researcher│    │
│  │ (多头研究员)   │  │ (空头研究员)  │    │
│  └──────────────┘  └──────────────┘     │
│                                          │
│  Phase 4: Risk & Sizing                  │
│  ┌──────────────┐  ┌──────────────┐     │
│  │ Quant Trader │  │ Risk Manager │     │
│  │ (量化交易员)  │  │ (风险管理官)  │    │
│  └──────────────┘  └──────────────┘     │
│                                          │
│  Phase 5: Final Decision                 │
│  ┌─────────────────────────────────┐    │
│  │      Fund Manager (基金经理)     │    │
│  │  Weighted scoring + veto logic   │    │
│  └─────────────────────────────────┘    │
└──────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────┐
│            Output Layer                   │
│  ┌─────────────┐  ┌──────────────────┐  │
│  │ Markdown     │  │ Rich Console     │  │
│  │ Report (.md) │  │ Formatter        │  │
│  └─────────────┘  └──────────────────┘  │
│  ┌─────────────┐  ┌──────────────────┐  │
│  │ Compliance   │  │ Copilot Plan     │  │
│  │ Logger       │  │ (pre-trading)    │  │
│  └─────────────┘  └──────────────────┘  │
└──────────────────────────────────────────┘
```

## 5-Phase Pipeline

### Phase 1: Data Pre-fetch
Collects all market data upfront via AKShare:
- **Price history** (250 days OHLCV)
- **Financial statements** (income, balance sheet, cash flow)
- **Technical indicators** (RSI, MACD, KDJ, Bollinger, etc.)
- **News & insider trades**
- **Portfolio state** (current cash, holdings, trade history from CSV)

### Phase 2: Independent Analysis (3 agents)
Three core analysts work independently, each receiving full portfolio context:

| Agent | Role | Weight | Focus |
|-------|------|--------|-------|
| **Fundamental Analyst** | 基本面分析师 | 40% | Revenue, margins, ROE, DCF valuation, PE/PB ratios |
| **Technical Analyst** | 技术面分析师 | 30% | MA crossovers, RSI, MACD, Bollinger, support/resistance |
| **Sentiment Analyst** | 情绪面分析师 | 30% | News sentiment, insider trades, capital flows |

Each outputs: `signal (BUY/SELL/HOLD)`, `score (0-10)`, `confidence (0-1)`, reasoning, key factors, risks.

### Phase 3: Bull/Bear Debate
Two research agents build opposing investment theses:

- **Bull Researcher** (多头研究员): Builds the strongest case FOR buying
- **Bear Researcher** (空头研究员): Builds the strongest case AGAINST buying

They receive all Phase 2 reports and generate scored theses. Net conviction = (bull_score - bear_score) / 10.

### Phase 4: Risk & Sizing
Quantitative risk assessment and position management:

- **Quant Trader** (量化交易员): Risk metrics (Sharpe, Sortino, VaR), recommended position size
- **Risk Manager** (风险管理官): **Veto power** — enforces position limits and drawdown limits

Risk limits (configurable):
- Max single position: 25% of portfolio
- Max sector concentration: 40%
- Max drawdown: 15%

### Phase 5: Final Decision
The **Fund Manager** (基金经理) synthesizes everything with a 7-step methodology:

1. **Score Extraction**: Read each analyst's score
2. **Weighted Calculation**: `fundamental×0.40 + technical×0.30 + sentiment×0.30`
3. **Vote Tally**: Count BUY/SELL/HOLD among 3 core analysts
4. **Bull/Bear Assessment**: Net conviction from debate
5. **Risk Check**: Honor Risk Manager's veto
6. **Decision Rules**: `weighted≥7.5 + 2 BUY votes → BUY`, `weighted≤3.5 + 2 SELL → SELL`, else `HOLD`
7. **Position Sizing**: Recommended shares (A-share 100-lot rounding)

## Project Structure

```
stock_agents/
├── __main__.py          # Entry point: python -m stock_agents
├── cli.py               # CLI with argparse + Rich terminal output
├── orchestrator.py      # 5-phase pipeline orchestrator
├── config.yaml          # Main configuration
├── portfolio.csv        # Trade log (your holdings)
│
├── agents/              # 8 AI analyst agents
│   ├── base.py          # BaseAgent ABC
│   ├── fundamental_analyst.py
│   ├── technical_analyst.py
│   ├── sentiment_analyst.py
│   ├── research_bull.py
│   ├── research_bear.py
│   ├── quant_trader.py
│   ├── risk_manager.py
│   └── fund_manager.py
│
├── llm/                 # LLM client backends
│   ├── __init__.py      # LLMClient Protocol + re-exports
│   ├── claude_client.py # Anthropic Claude API
│   ├── github_models_client.py  # GitHub Models (GPT-4o, Claude via Azure)
│   ├── ollama_client.py # Local Ollama fallback
│   └── fallback_client.py  # Auto-fallback wrapper
│
├── config/              # Configuration
│   ├── settings.py      # Pydantic settings (YAML + .env)
│   └── prompts.py       # System prompts for all 8 agents
│
├── data/                # Data acquisition
│   ├── data_manager.py  # Unified data interface
│   ├── akshare_client.py  # A-share market data (AKShare)
│   ├── csv_portfolio.py # CSV-based portfolio tracker
│   ├── cache.py         # File-based JSON cache (TTL)
│   ├── futu_client.py   # Futu OpenD broker client
│   └── ths_client.py    # THS file-based account reader
│
├── models/              # Pydantic data models
│   ├── market_data.py   # OHLCVBar, StockSnapshot, FinancialData, TechnicalIndicators
│   ├── portfolio.py     # Position, PortfolioState, RiskMetrics
│   └── signals.py       # AgentReport, DebateReport, FinalDecision
│
├── indicators/          # Quantitative computation
│   ├── technical.py     # KDJ, RSI, MACD, Bollinger, SMA/EMA, ATR
│   └── risk_metrics.py  # Sharpe, Sortino, max drawdown, VaR, beta
│
├── output/              # Reporting
│   ├── report_generator.py  # Full Markdown analysis reports
│   ├── formatters.py    # Rich console output
│   └── copilot_plan.py  # Pre-trading action plans
│
├── compliance/          # Audit trail
│   └── logger.py        # JSONL compliance logs
│
├── tests/               # Test suite
│   ├── test_data.py     # Market data + trading hours
│   ├── test_portfolio.py  # CSV portfolio + trade history
│   ├── test_indicators.py # Technical indicators + risk metrics
│   ├── test_llm.py      # LLM client Protocol + fallback logic
│   ├── test_config.py   # Settings + prompts
│   └── test_agents.py   # Agent reports + report generation
│
├── reports/             # Generated .md analysis reports
├── logs/                # Compliance JSONL logs
└── .cache/              # Cached API responses (JSON, TTL-based)
```

## Quick Start

### Prerequisites
- Python 3.11+
- GitHub Token (for GitHub Models API) or Anthropic API key

### Installation

```bash
pip install -r requirements.txt
```

### Configuration

1. Copy `.env.example` to `.env` and add your API key:
```bash
GITHUB_TOKEN=ghp_your_github_pat_here
```

2. Edit `config.yaml`:
```yaml
llm:
  provider: github_models   # or "anthropic" or "ollama"
  model: gpt-4o
  model_final: gpt-4o
  fallback: ollama           # auto-fallback to local Ollama on API errors

watchlist:
  - "603993"                 # Stock codes to analyze

risk:
  max_single_position_pct: 0.25
  max_drawdown_pct: 0.15
```

3. Record your portfolio in `portfolio.csv`:
```csv
date,action,symbol,name,shares,price,commission,note
2026-04-08,init_cash,,,,,55351.10,初始资金
2026-04-08,buy,603993,洛阳钼业,1100,17.956,5.00,建仓
```

### Usage

```bash
# Analyze a single stock
python -m stock_agents analyze 603993

# Analyze entire watchlist
python -m stock_agents watchlist

# Generate pre-trading plan
python -m stock_agents plan
```

### Running Tests

```bash
# All offline tests (no API/network needed)
python -m pytest stock_agents/tests/ -v -k "not Ollama and not GitHub"

# Including network tests (market data)
python -m pytest stock_agents/tests/ -v

# Specific module
python -m pytest stock_agents/tests/test_indicators.py -v
```

## LLM Backend Options

| Provider | Config | Notes |
|----------|--------|-------|
| **GitHub Models** | `provider: github_models` | Free with Copilot Pro, uses GPT-4o/Claude via Azure |
| **Anthropic** | `provider: anthropic` | Direct Claude API, needs `ANTHROPIC_API_KEY` |
| **Ollama** | `provider: ollama` | Local, free, slower. Default model: gemma3 |
| **Fallback** | `fallback: ollama` | Auto-switches to Ollama after 3 consecutive cloud failures |

## Report Output

Each analysis generates a comprehensive Markdown report with:
- Your current portfolio state (cash, holdings, P&L)
- Each agent's complete analysis (reasoning, scores, key factors, risks)
- Full agent raw data in expandable sections
- Bull/Bear debate with scored theses
- Fund Manager's step-by-step decision methodology
- Position sizing recommendation with target price and stop loss

Reports are saved to `reports/` directory.

## Data Flow

```
portfolio.csv ──► DataManager ──► All 8 Agents (portfolio context)
                      │
AKShare API ────► DataManager ──► Phase 2 Agents (market data)
                      │
                  Indicators ──► Technical/Risk computation
                      │
                  Cache (.json) ◄── TTL-based (15min default)
```

Every agent receives the user's portfolio context (cash, positions, avg cost, trade history) so their analysis accounts for the user's actual situation.

## Disclaimer

This is an AI-powered analysis tool for educational and research purposes. All outputs are generated by LLM agents and should not be treated as financial advice. Always do your own research before making investment decisions.
