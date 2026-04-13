# Stock Agents — 多周期 AI 股票分析系统

A multi-agent AI system for China A-share stock analysis. Eight specialist AI agents — each embodying the decision philosophy of a real financial legend — collaborate through a structured 5-phase pipeline to produce buy/sell/hold recommendations across three investment horizons: short-term (≤1 month), mid-term (1–6 months), and long-term (6 months+).

**Core principle: Code computes, AI decides.** All quantitative math (Kelly criterion, Graham valuation, technical signals, risk assessment) is pre-computed by a deterministic quant engine. LLM agents only interpret and synthesize — they never do arithmetic.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture](#architecture)
3. [Three-Horizon System](#three-horizon-system)
4. [Agent Philosophies](#agent-philosophies)
5. [5-Phase Pipeline](#5-phase-pipeline)
6. [Quant Engine](#quant-engine)
7. [LLM Backends](#llm-backends)
8. [CLI Reference](#cli-reference)
9. [Portfolio Tracking](#portfolio-tracking)
10. [Configuration](#configuration)
11. [Project Structure](#project-structure)

---

## Quick Start

### Requirements

- Python 3.11+
- One of: Azure OpenAI endpoint, GitHub Copilot Pro account, Anthropic API key, or local [Ollama](https://ollama.com)

### Install

```bash
cd stock_agents
pip install -e .
```

### Configure

Create a `.env` file in `stock_agents/`:

```env
# Azure OpenAI (HP Corporate / enterprise)
AZURE_OPENAI_API_KEY=your_key
HP_UID_CLIENT_ID=your_uid_client_id
HP_UID_CLIENT_SECRET=your_uid_client_secret

# OR: GitHub Models / Copilot Pro
COPILOT_GITHUB_TOKEN=your_fine_grained_pat

# OR: Anthropic Claude
ANTHROPIC_API_KEY=your_key

# OR: Ollama runs locally, no key needed
```

Edit `config.yaml` to select your LLM provider and set your watchlist:

```yaml
llm:
  provider: "azure_openai"   # azure_openai | github_models | anthropic | ollama | openrouter
  model: "gpt-54"
  fallback: "ollama"

watchlist:
  - "600711"   # 盛屯矿业
  - "601012"   # 隆基绿能
  - "603993"   # 洛阳钼业
```

Record your initial cash in `portfolio.csv`:

```csv
date,action,symbol,name,shares,price,commission,note
2026-04-08,init_cash,,,,,55351.10,初始资金
```

### Run

```bash
# Analyze one stock (balanced single-team analysis)
python -m stock_agents analyze 600711

# Run all three horizon teams simultaneously (full 三周期 analysis)
python -m stock_agents analyze 600711 --horizon all

# Single horizon
python -m stock_agents analyze 600711 --horizon short
python -m stock_agents analyze 600711 --horizon mid
python -m stock_agents analyze 600711 --horizon long

# Analyze entire watchlist
python -m stock_agents watchlist
python -m stock_agents watchlist --horizon all

# Portfolio snapshot, trade recording, pre-market plan
python -m stock_agents portfolio
python -m stock_agents trade buy 600711 700 14.15
python -m stock_agents copilot-plan
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLI  /  MCP Server                           │
│              python -m stock_agents  |  mcp_server.py               │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
          ┌────────────┴─────────────┐
          │                          │
          ▼                          ▼
  ┌───────────────┐        ┌──────────────────────┐
  │  Orchestrator │        │ MultiHorizonOrch.     │
  │ (single team) │        │ (3 horizon teams)     │
  └───────┬───────┘        └──────────┬───────────┘
          │                           │
          └──────────┬────────────────┘
                     │
     ┌───────────────▼──────────────────────────┐
     │              Data Layer                   │
     │  AKShare (市场数据)  ·  CSV Portfolio      │
     │  File Cache (JSON, TTL=15min)             │
     │  THS / Futu (broker account readers)     │
     └───────────────┬──────────────────────────┘
                     │
     ┌───────────────▼──────────────────────────┐
     │           Quant Engine                    │
     │  (pre-computed before any LLM call)       │
     │  Kelly criterion  ·  Graham valuation     │
     │  Technical signals  ·  Risk assessment    │
     │  Composite score  ·  Position sizing      │
     └───────────────┬──────────────────────────┘
                     │
     ┌───────────────▼──────────────────────────┐
     │          8 Analyst Agents                 │
     │                                           │
     │  Phase 2  —  Independent Analysis         │
     │    FundamentalAnalyst  (Graham+Simons)    │
     │    TechnicalAnalyst    (Simons)           │
     │    SentimentAnalyst    (Dalio)            │
     │                                           │
     │  Phase 3  —  Bull/Bear Debate             │
     │    BullResearcher      (Kraus)            │
     │    BearResearcher      (Taleb)            │
     │                                           │
     │  Phase 4  —  Risk & Sizing                │
     │    QuantTrader         (Simons)           │
     │    RiskManager         (Taleb+Markowitz)  │
     │                                           │
     │  Phase 5  —  Final Decision               │
     │    FundManager         (Wooldridge MAS)   │
     └───────────────┬──────────────────────────┘
                     │
     ┌───────────────▼──────────────────────────┐
     │           LLM Backends                    │
     │  Azure OpenAI (GPT-5.4)  [primary]       │
     │  GitHub Models / Copilot Pro             │
     │  Anthropic Claude                        │
     │  Ollama  (local fallback)                │
     │  FallbackClient  (auto rate-limit retry) │
     └───────────────┬──────────────────────────┘
                     │
     ┌───────────────▼──────────────────────────┐
     │             Output                        │
     │  Rich console  ·  Markdown reports        │
     │  Compliance JSONL log  ·  Copilot plan    │
     └──────────────────────────────────────────┘
```

---

## Three-Horizon System

When you pass `--horizon all`, three independent teams analyze the same stock simultaneously, each with different priorities, weights, and risk tolerances.

```
┌─────────────────┬──────────────────┬──────────────────┬──────────────────┐
│ 参数            │  短线 (≤1月)     │  中线 (1-6月)    │  长线 (6月+)     │
├─────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ 技术面权重       │ 45%  (主导)      │ 25%              │ 15%              │
│ 基本面权重       │ 10%              │ 35%              │ 50%  (主导)      │
│ 成长性权重       │ 10%              │ 15%              │ 25%              │
│ 风险权重         │ 35%              │ 25%              │ 10%              │
├─────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ 买入阈值         │ ≥ 6.5           │ ≥ 7.0            │ ≥ 7.5            │
│ 卖出阈值         │ ≤ 3.5           │ ≤ 3.5            │ ≤ 3.0            │
│ 止损 (ATR倍数)   │ 1.5×            │ 2.0×             │ 3.0×             │
│ Kelly上限        │ 20%             │ 25%              │ 15%              │
│ 最大单仓         │ 8%              │ 10%              │ 15%              │
│ 最大回撤限制     │ 8%              │ 12%              │ 20%              │
└─────────────────┴──────────────────┴──────────────────┴──────────────────┘
```

**Consensus rule**: 2 of 3 horizons agree → that action. Otherwise → HOLD.

**Output**: three-column comparison table plus consensus summary:

```
                    短线 vs 中线 vs 长线
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ 指标       ┃   短线 (≤1月) ┃  中线 (1-6月) ┃   长线 (6月+) ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ 建议       │   HOLD (83%)  │   HOLD (84%)  │   HOLD (86%)  │
│ 基本面     │      5.4      │      5.4      │      5.0      │
│ 技术面     │      4.8      │      4.8      │      4.2      │
│ 情绪面     │      6.8      │      6.8      │      7.1      │
│ 目标价     │     14.60     │     15.09     │     14.60     │
│ 止损价     │     13.09     │     12.73     │     12.02     │
│ 建议仓位   │     13.9%     │     10.2%     │      8.0%     │
└────────────┴───────────────┴───────────────┴───────────────┘

三周期一致：HOLD。短线 83%，中线 84%，长线 86%。综合建议：HOLD。
```

Data is fetched once and shared across all three teams. Horizons run sequentially (API rate limit safety); agents within each horizon run through a serialized semaphore with 2s delay between calls.

---

## Agent Philosophies

Each agent's system prompt is grounded in the actual decision framework of a real financial legend. The LLM interprets pre-computed quant data through that lens — it does no arithmetic itself.

| Agent | Financial Mind | Core Philosophy Applied |
|-------|---------------|------------------------|
| **FundamentalAnalyst** | Ben Graham + Jim Simons | Margin of safety, Graham formula V=EPS×(8.5+2g), statistical edge over narrative |
| **TechnicalAnalyst** | Jim Simons (Renaissance) | Pattern recognition as signal extraction, momentum + mean reversion, zero narrative bias |
| **SentimentAnalyst** | Ray Dalio | Macro narrative analysis, news as leading indicator, "what would change the machine's view" |
| **BullResearcher** | Cliff Asness (AQR) | Factor investing, value + momentum game theory, build strongest BUY case |
| **BearResearcher** | Nassim Nicholas Taleb | Antifragility, fat tail identification, "what is the maximum credible loss path" |
| **QuantTrader** | Jim Simons | Kelly criterion sizing, factor scores, mathematical position recommendation |
| **RiskManager** | Taleb + Harry Markowitz | Portfolio-level risk, drawdown control, correlation — has **veto power** |
| **FundManager** | Michael Wooldridge (MAS) | Multi-agent coordination, structured voting, conflict resolution, final synthesizer |

Each horizon team gets a Chinese-language preamble prepended to the base prompt, shifting focus toward the horizon's investment timeframe (e.g., short-term emphasizes technical pattern and momentum; long-term emphasizes earnings quality and business moat).

---

## 5-Phase Pipeline

Each analysis (per stock, per horizon) runs through five phases.

### Phase 0 — Quant Engine (before any LLM)

The deterministic quant engine pre-computes everything numeric:

```
raw market data
    ├── Technical signals: RSI zone, MACD crossover, KDJ state, Bollinger squeeze, ATR
    ├── Fundamental signals: Graham intrinsic value, PE/PB z-score, ROE quality, Piotroski F-Score
    ├── Kelly criterion: f* = (bp - q) / b, capped per horizon, half-Kelly applied
    ├── Risk assessment: max drawdown vs limit, VaR, Sharpe/Sortino, concentration check
    └── Composite score (0-10): weighted sum of all factors per horizon
```

All four result sections are injected into every agent's context as structured JSON (not prose).

### Phase 1 — Data Pre-fetch

AKShare fetches and caches (15 min TTL):
- 250-day OHLCV price history
- 8 quarters of financial statements (income, balance sheet, cash flow)
- Calculated technical indicators (RSI, MACD, KDJ, Bollinger, SMA/EMA, ATR)
- 20 recent news items and insider trades
- Portfolio state from `portfolio.csv` (cash, positions, avg cost, trade history)

### Phase 2 — Independent Analysis (3 agents)

Three core analysts work independently, each receiving full market data + pre-computed quant signals:

| Agent | Default Weight | Focus |
|-------|---------------|-------|
| FundamentalAnalyst | 40% | Valuation vs intrinsic value, earnings quality, growth runway |
| TechnicalAnalyst | 30% | Chart structure, momentum, support/resistance levels |
| SentimentAnalyst | 30% | News sentiment, capital flow, macro positioning |

Each outputs: `signal` (BUY/SELL/HOLD), `score` (0–10), `confidence` (0–1), `reasoning`, `key_factors`, `risks`.

### Phase 3 — Bull/Bear Debate

BullResearcher builds the strongest case FOR buying; BearResearcher the strongest case AGAINST. Both receive Phase 2 reports. Net conviction = `(bull_score − bear_score) / 10`.

### Phase 4 — Risk & Sizing (sequential)

1. **QuantTrader**: Kelly fraction → concrete share count (100-lot rounded for A-shares)
2. **RiskManager**: checks portfolio drawdown, concentration, sector limits. **Veto power** — `risk_approved=False` forces HOLD regardless of other signals.

### Phase 5 — Final Decision (FundManager)

Seven-step synthesis:

```
1. Extract each analyst's score and signal
2. Weighted score = fundamental×w₁ + technical×w₂ + sentiment×w₃
3. Vote tally: count BUY / SELL / HOLD among 3 core analysts
4. Bull/Bear net conviction assessment
5. Risk veto check (risk_approved=False → HOLD regardless)
6. Decision rules:
     composite ≥ buy_threshold  AND  2+ BUY votes  →  BUY
     composite ≤ sell_threshold  AND  2+ SELL votes  →  SELL
     otherwise                                        →  HOLD
7. Position sizing: Kelly shares, rounded to 100-lot multiples
```

---

## Quant Engine

`indicators/quant_engine.py` is the math backbone. Call it directly:

```python
from stock_agents.indicators.quant_engine import run_quant_pipeline

signals = run_quant_pipeline(
    indicators=ind_dict,        # RSI, MACD, KDJ, ATR, etc.
    financials=fin_dict,        # PE, PB, ROE, EPS, margins, growth rates
    risk_metrics=risk_dict,     # max_drawdown, sharpe, portfolio positions
    current_price=14.17,
    market_cap=8.5e9,
    portfolio_value=100000,
    portfolio_positions=[...],
    atr=0.35,
    # Horizon-specific overrides:
    horizon_weights={"fundamental": 0.10, "technical": 0.45, "growth": 0.10, "risk": 0.35},
    kelly_cap=0.20,
    buy_threshold=6.5,
    sell_threshold=3.5,
    stop_loss_atr_mult=1.5,
    hold_period_days=20,
)

# Returns four sub-dicts:
signals["technical_signal"]    # RSI zone, MACD crossover, KDJ state, trend direction
signals["fundamental_signal"]  # Graham value vs price, F-Score, margin quality
signals["quant_signal"]        # Kelly fraction, composite score, recommended shares
signals["risk_signal"]         # Drawdown vs limit, VaR, risk_approved bool
```

---

## LLM Backends

Configure `llm.provider` in `config.yaml`:

| Provider | `provider` value | Notes |
|----------|-----------------|-------|
| **Azure OpenAI** | `azure_openai` | HP corporate endpoint, GPT-5.4, HP UID OAuth bearer auth |
| **GitHub Models** | `github_models` | Free with Copilot Pro. GPT-4o via Azure. Full catalog needs fine-grained PAT |
| **Anthropic** | `anthropic` | Claude 3.5/3.7. Needs `ANTHROPIC_API_KEY` |
| **Ollama** | `ollama` | Local, free, no network. `gemma4` recommended |
| **OpenRouter** | `openrouter` | Access to many models. Needs `OPENROUTER_API_KEY` |

### Fallback behavior

`FallbackLLMClient` wraps any primary + secondary pair:

- **Rate limits (429)**: triggers 60s backoff and retry on primary — does **not** count toward permanent switch
- **Real errors** (auth, config, model not found): counted; 3 consecutive → permanently switch to fallback for the session
- Resets to primary on successful call

### Azure OpenAI (HP Corporate)

```env
HP_UID_CLIENT_ID=your_client_id
HP_UID_CLIENT_SECRET=your_client_secret
AZURE_OPENAI_API_KEY=your_key   # fallback if UID auth unavailable
```

The client auto-fetches an HP UID OAuth bearer token (30 min expiry, auto-refreshed) and loads the HP corporate CA certificate bundle from `ca-certifacates.crt`.

### GitHub Models / Copilot Pro

Use a **fine-grained PAT** (not classic `ghp_*`) with the "Copilot Requests" permission:

```env
COPILOT_GITHUB_TOKEN=github_pat_...
```

Classic PATs are automatically downgraded to the free GitHub Models endpoint (GPT-4o only).

---

## CLI Reference

```
python -m stock_agents <command> [options]
```

### `analyze <symbol>`

Full 5-phase analysis for one stock.

```bash
python -m stock_agents analyze 600711
python -m stock_agents analyze 600711 --horizon short   # short-term team only
python -m stock_agents analyze 600711 --horizon mid     # mid-term team only
python -m stock_agents analyze 600711 --horizon long    # long-term team only
python -m stock_agents analyze 600711 --horizon all     # all three teams + consensus
```

### `watchlist`

Analyze all stocks in `config.yaml watchlist`.

```bash
python -m stock_agents watchlist
python -m stock_agents watchlist --horizon all
```

### `portfolio`

Show current portfolio snapshot: positions, P&L, cash, total value.

```bash
python -m stock_agents portfolio
```

### `trade`

Record trades or set cash. Persisted to `portfolio.csv`.

```bash
python -m stock_agents trade buy  600711 700 14.15 --commission 5.00
python -m stock_agents trade sell 600711 300 15.50 --commission 3.00
python -m stock_agents trade cash 55000       # set cash balance
python -m stock_agents trade history          # print trade log
```

### `copilot-plan`

Generate a pre-market action plan for all watchlist stocks.

```bash
python -m stock_agents copilot-plan
python -m stock_agents copilot-plan --save-plan
```

### `config`

Print current resolved configuration.

```bash
python -m stock_agents config
```

### Global flags

```bash
python -m stock_agents -v analyze 600711       # verbose logging
python -m stock_agents --config my.yaml ...   # custom config file
```

---

## Portfolio Tracking

`portfolio.csv` is the source of truth for your holdings. All agents receive portfolio context so their recommendations account for your actual situation (existing positions, avg cost, drawdown, available cash).

### File format

```csv
date,action,symbol,name,shares,price,commission,note
2026-04-08,init_cash,,,,,55351.10,初始资金
2026-04-08,buy,603993,洛阳钼业,1100,17.956,5.00,建仓
2026-04-10,buy,600711,盛屯矿业,700,14.150,3.50,加仓
2026-04-11,sell,603993,洛阳钼业,300,18.500,2.00,减仓
```

### Actions

| action | Description |
|--------|-------------|
| `init_cash` | Set initial capital (amount goes in `commission` column) |
| `buy` | Purchase shares |
| `sell` | Sell shares |
| `adjust_cash` | Manual adjustment (dividends, fees, transfers) |

### Context provided to agents

Every agent receives:
- Available cash and total portfolio value
- All open positions: symbol, shares, avg cost, current price, unrealized P&L
- Full trade history
- Current portfolio drawdown vs configured limit

---

## Configuration

All settings in `config.yaml`. Override via `.env` or environment variables.

```yaml
llm:
  provider: "azure_openai"          # LLM backend
  model: "gpt-54"                   # Model for analyst agents (Phases 2-4)
  model_final: "gpt-54"            # Model for FundManager (Phase 5)
  max_tokens: 4096
  temperature: 0.3
  endpoint: "https://..."           # Azure endpoint URL
  azure_deployment: "gpt-54"
  fallback: "ollama"                # Fallback provider on primary failure

ollama:
  model: "gemma4"
  endpoint: "http://localhost:11434/v1"

watchlist:
  - "600711"
  - "601012"
  - "603993"

analysis:
  lookback_days: 250               # Price history window
  financial_quarters: 8           # Earnings history depth
  news_count: 20

risk:
  max_single_position_pct: 0.25   # 25% max per position
  max_sector_pct: 0.40            # 40% max per sector
  max_drawdown_pct: 0.15          # 15% drawdown triggers risk veto
  total_capital: 75103            # Auto-calculated from portfolio.csv

cache:
  enabled: true
  ttl_seconds: 900                # 15-minute TTL for market data
  directory: ".cache"

output:
  save_to_file: true
  output_directory: "reports"
```

---

## Project Structure

```
stock_agents/
├── __main__.py              # Entry point
├── cli.py                   # CLI commands + Rich console output
├── orchestrator.py          # Single-team 5-phase pipeline
├── multi_horizon.py         # Three-horizon orchestrator (SHORT/MID/LONG)
├── mcp_server.py            # MCP server for GitHub Copilot integration
├── config.yaml              # Main configuration
├── portfolio.csv            # Your trade log (source of truth for holdings)
│
├── agents/                  # 8 AI analyst agents
│   ├── base.py              # BaseAgent ABC: gather_data() + analyze()
│   ├── fundamental_analyst.py   # Philosophy: Ben Graham + Jim Simons
│   ├── technical_analyst.py     # Philosophy: Jim Simons (Renaissance)
│   ├── sentiment_analyst.py     # Philosophy: Ray Dalio
│   ├── research_bull.py         # Philosophy: Cliff Asness (AQR)
│   ├── research_bear.py         # Philosophy: Nassim Taleb
│   ├── quant_trader.py          # Philosophy: Jim Simons (Kelly sizing)
│   ├── risk_manager.py          # Philosophy: Taleb + Markowitz (veto power)
│   └── fund_manager.py          # Philosophy: Wooldridge MAS (synthesis)
│
├── config/
│   ├── settings.py          # Pydantic settings model (YAML + .env)
│   ├── prompts.py           # System prompts for all 8 agents + get_horizon_prompt()
│   └── horizons.py          # SHORT/MID/LONG HorizonConfig presets
│
├── indicators/
│   ├── technical.py         # KDJ, RSI, MACD, Bollinger, SMA/EMA, ATR
│   ├── risk_metrics.py      # Sharpe, Sortino, max drawdown, VaR, beta
│   └── quant_engine.py      # Unified quant pipeline: Kelly, Graham, composite score
│
├── llm/
│   ├── __init__.py          # LLMClient Protocol (duck-typed interface)
│   ├── azure_openai_client.py   # Azure OpenAI + HP UID OAuth + cert handling
│   ├── github_models_client.py  # GitHub Models / Copilot Pro API
│   ├── claude_client.py         # Anthropic Claude
│   ├── ollama_client.py         # Local Ollama (OpenAI-compatible)
│   ├── openrouter_client.py     # OpenRouter
│   └── fallback_client.py       # Rate-limit-aware auto-fallback wrapper
│
├── data/
│   ├── data_manager.py      # Unified data interface (all agents call this)
│   ├── akshare_client.py    # A-share market data via AKShare
│   ├── csv_portfolio.py     # Trade log reader + portfolio state calculator
│   ├── cache.py             # File-based JSON cache with TTL
│   ├── futu_client.py       # Futu OpenD broker client
│   └── ths_client.py        # THS file-based account reader
│
├── models/
│   ├── market_data.py       # OHLCVBar, StockSnapshot, FinancialData, TechnicalIndicators
│   ├── portfolio.py         # Position, PortfolioState, RiskMetrics
│   └── signals.py           # AgentReport, DebateReport, FinalDecision, MultiHorizonDecision
│
├── output/
│   ├── formatters.py        # Rich console tables (single + multi-horizon display)
│   ├── report_generator.py  # Full Markdown analysis report generator
│   └── copilot_plan.py      # Pre-trading action plan generator
│
├── compliance/
│   └── logger.py            # JSONL audit log — every decision persisted
│
├── tests/
│   ├── test_data.py         # Market data fetch, trading hours
│   ├── test_portfolio.py    # CSV portfolio, trade history
│   ├── test_indicators.py   # Technical indicators, risk metrics
│   ├── test_llm.py          # LLM Protocol, fallback logic
│   ├── test_config.py       # Settings loading, prompts
│   ├── test_agents.py       # Agent output schema, report generation
│   └── test_realtime_price.py  # Real-time price polling (10x, 10s interval)
│
├── reports/                 # Generated Markdown reports (gitignored)
├── logs/                    # Compliance JSONL logs (gitignored)
└── .cache/                  # Cached API responses (gitignored)
```

---

## Running Tests

```bash
cd stock_agents
pytest tests/ -v                          # all tests
pytest tests/ -v -k "not realtime"       # skip real-time price polling
pytest tests/test_indicators.py -v       # quant engine + technical indicators
pytest tests/test_portfolio.py -v        # portfolio tracking
```

---

## Disclaimer

This is an AI-powered research tool for educational and research purposes. All outputs are generated by LLM agents interpreting market data and do **not** constitute financial advice. Past model recommendations do not guarantee future returns. Always conduct your own due diligence before making investment decisions.
