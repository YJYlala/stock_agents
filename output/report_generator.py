"""Report generator - produces comprehensive Markdown analysis reports.

Shows portfolio context, each agent's full output, and the fund manager's
complete decision with methodology. No fixed template — natural document flow.
"""

from datetime import datetime
from pathlib import Path

from stock_agents.models.signals import AgentReport, FinalDecision


def _fmt_number(v, decimals=2) -> str:
    """Format a number for display."""
    if v is None:
        return "N/A"
    if isinstance(v, float):
        if abs(v) >= 1e8:
            return f"{v/1e8:.2f}亿"
        if abs(v) >= 1e4:
            return f"{v/1e4:.2f}万"
        return f"{v:.{decimals}f}"
    return str(v)


def _render_data_section(data: dict) -> str:
    """Render the full data_used dict for one agent."""
    if not data:
        return "> 无原始数据\n"

    lines = []
    simple = {}
    nested = {}
    for k, v in data.items():
        if isinstance(v, (dict, list)):
            nested[k] = v
        else:
            simple[k] = v

    if simple:
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        for k, v in simple.items():
            lines.append(f"| {k} | {_fmt_number(v)} |")
        lines.append("")

    for key, val in nested.items():
        if isinstance(val, dict):
            lines.append(f"\n**{key}:**\n")
            lines.append("| 指标 | 数值 |")
            lines.append("|------|------|")
            for k2, v2 in val.items():
                if isinstance(v2, (dict, list)):
                    lines.append(f"| {k2} | *(详见下方)* |")
                else:
                    lines.append(f"| {k2} | {_fmt_number(v2)} |")
            lines.append("")
            for k2, v2 in val.items():
                if isinstance(v2, dict):
                    lines.append(f"\n*{key}.{k2}:*\n")
                    lines.append("| 指标 | 数值 |")
                    lines.append("|------|------|")
                    for k3, v3 in v2.items():
                        lines.append(f"| {k3} | {_fmt_number(v3)} |")
                    lines.append("")
        elif isinstance(val, list):
            if len(val) > 0 and isinstance(val[0], dict):
                lines.append(f"\n**{key}** ({len(val)} 条):\n")
                show = val if len(val) <= 25 else val[:10]
                if len(val) > 25:
                    lines.append(f"> 共 {len(val)} 条，显示前 10 条")
                headers = list(show[0].keys())
                lines.append("| " + " | ".join(headers) + " |")
                lines.append("|" + "|".join(["------"] * len(headers)) + "|")
                for item in show:
                    row = " | ".join(str(item.get(h, ""))[:60] for h in headers)
                    lines.append(f"| {row} |")
                lines.append("")
            else:
                lines.append(f"\n**{key}:** {val}\n")

    return "\n".join(lines)


# Keys that are shared across all agents and should only appear once in report
_SHARED_DATA_KEYS = {
    "market_context", "curated_news", "news", "portfolio",
    "quant_signals", "prior_analyst_signals",
}


def _render_agent(report: AgentReport, compact: bool = True) -> str:
    """Render one agent's complete analysis.

    If compact=True, strips shared/duplicated data keys from raw data
    (they are rendered once in a dedicated section instead).
    """
    signal_icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(report.signal, "⚪")

    factors = "\n".join(f"- {f}" for f in report.key_factors) if report.key_factors else "N/A"
    risks = "\n".join(f"- {r}" for r in report.risks) if report.risks else "N/A"

    # Strip shared data from per-agent raw data to avoid duplication
    data = report.data_used
    if compact and data:
        data = {k: v for k, v in data.items() if k not in _SHARED_DATA_KEYS}

    data_section = _render_data_section(data) if data else "> 无独立数据\n"

    return f"""## {signal_icon} {report.agent_name} ({report.agent_role})

**信号: {report.signal} | 评分: {_fmt_number(report.score, 1)}/10 | 置信度: {f'{report.confidence:.0%}' if report.confidence is not None else 'N/A'}**

{report.reasoning}

**关键因素:**
{factors}

**风险因素:**
{risks}

<details>
<summary>📊 该代理独立数据</summary>

{data_section}

</details>

---

"""


def _render_portfolio_section(decision: FinalDecision) -> str:
    """Render the user's portfolio state and trade history."""
    portfolio = decision.portfolio_snapshot
    if not portfolio:
        return ""

    lines = ["## 我的持仓情况\n"]
    lines.append("| 项目 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 总资产 | CNY {_fmt_number(portfolio.get('total_value', 0))} |")
    lines.append(f"| 可用现金 | CNY {_fmt_number(portfolio.get('cash', 0))} |")

    positions = portfolio.get("positions", [])
    if positions:
        holdings_value = sum(p.get("market_value", 0) for p in positions)
        lines.append(f"| 持股市值 | CNY {_fmt_number(holdings_value)} |")
        lines.append(f"| 浮动盈亏 | CNY {_fmt_number(portfolio.get('total_unrealized_pnl', 0))} |")
        lines.append("")

        lines.append("\n### 当前持仓\n")
        lines.append("| 代码 | 名称 | 股数 | 均价 | 现价 | 市值 | 盈亏 | 盈亏% | 占比 |")
        lines.append("|------|------|------|------|------|------|------|-------|------|")
        for p in positions:
            pnl = p.get("unrealized_pnl", 0)
            pnl_pct = p.get("unrealized_pnl_pct", 0)
            lines.append(
                f"| {p.get('symbol','')} | {p.get('name','')[:8]} "
                f"| {p.get('shares',0)} | {p.get('avg_cost',0):.3f} "
                f"| {p.get('current_price',0):.3f} | {_fmt_number(p.get('market_value',0))} "
                f"| {pnl:+,.2f} | {pnl_pct:+.2f}% | {p.get('weight_pct',0):.1f}% |"
            )
    else:
        lines.append(f"| 持股市值 | CNY 0 |")
    lines.append("")

    # Trade history
    trades = decision.trade_history
    if trades:
        lines.append("\n### 交易记录\n")
        lines.append("| 日期 | 操作 | 代码 | 名称 | 股数 | 价格 | 手续费 | 备注 |")
        lines.append("|------|------|------|------|------|------|--------|------|")
        for t in trades:
            action_cn = "买入" if t["action"] == "buy" else "卖出"
            lines.append(
                f"| {t['date']} | {action_cn} | {t['symbol']} | {t['name']} "
                f"| {t['shares']} | {t['price']:.3f} | {t['commission']:.2f} | {t['note']} |"
            )
        lines.append("")

    lines.append("\n---\n")
    return "\n".join(lines)


def _render_shared_data_section(agent_reports: list[AgentReport]) -> str:
    """Extract shared data (market context, quant signals, etc.) from first agent and render once."""
    if not agent_reports:
        return ""

    # Find the first agent that has data_used
    source = None
    for r in agent_reports:
        if r.data_used:
            source = r.data_used
            break
    if not source:
        return ""

    lines = []

    # Market context (formatted text block)
    mc = source.get("market_context")
    if mc and isinstance(mc, str) and len(mc) > 20:
        lines.append("## 📈 市场环境\n")
        lines.append(mc)
        lines.append("")

    # Quant signals
    qs = source.get("quant_signals")
    if qs and isinstance(qs, dict):
        lines.append("\n## 📐 量化信号\n")
        lines.append(_render_data_section({"quant_signals": qs}))
        lines.append("")

    # Curated news
    cn = source.get("curated_news")
    if cn and isinstance(cn, dict):
        lines.append("\n## 📰 AI新闻摘要\n")
        if cn.get("init_summary"):
            lines.append(f"> {cn['init_summary']}\n")
        useful = cn.get("useful_news", [])
        if useful:
            lines.append("**精选新闻:**\n")
            for i, n in enumerate(useful[:10], 1):
                if isinstance(n, dict):
                    lines.append(f"{i}. {n.get('title', n.get('content', str(n)))}")
                else:
                    lines.append(f"{i}. {n}")
            lines.append("")
        if cn.get("risk_flags"):
            lines.append(f"**风险信号:** {', '.join(cn['risk_flags'])}\n")
        if cn.get("sentiment_summary"):
            lines.append(f"**情绪总结:** {cn['sentiment_summary']}\n")

    # Company announcements
    ann = source.get("announcements")
    if ann and isinstance(ann, list) and len(ann) > 0:
        lines.append("\n## 📋 公司公告\n")
        for item in ann[:10]:
            if isinstance(item, dict):
                title = item.get("公告标题", item.get("title", ""))
                date = item.get("公告日期", item.get("date", ""))
                cat = item.get("公告类型", item.get("type", ""))
                lines.append(f"- [{date}] {title}" + (f" ({cat})" if cat else ""))
            else:
                lines.append(f"- {item}")
        lines.append("")

    if not lines:
        return ""

    return "\n".join(lines) + "\n---\n\n"


def generate_report(decision: FinalDecision) -> str:
    """Generate a comprehensive Markdown report with fund manager decision FIRST."""
    # Compute weighted score from available components
    score_parts = []
    weights_parts = []
    f_score = decision.fundamental_score
    t_score = decision.technical_score
    s_score = decision.sentiment_score
    if f_score is not None:
        score_parts.append(f_score * 0.40)
        weights_parts.append(0.40)
    if t_score is not None:
        score_parts.append(t_score * 0.30)
        weights_parts.append(0.30)
    if s_score is not None:
        score_parts.append(s_score * 0.30)
        weights_parts.append(0.30)
    total_w = sum(weights_parts)
    weighted_score = sum(score_parts) / total_w * 1.0 if total_w > 0 else None

    # ── Header
    model_label = decision.llm_model or "未知模型"
    report = f"""# {decision.name} ({decision.symbol}) 分析报告

> 生成时间: {decision.timestamp.strftime("%Y-%m-%d %H:%M")} | 模型: {model_label}

---

"""

    # ── Fund Manager final decision (FIRST — most important)
    conf_str = f"{decision.confidence:.0%}" if decision.confidence is not None else "N/A"

    def _score_row(label, score, weight_pct):
        if score is None:
            return f"| {label} | N/A | {weight_pct}% | N/A |"
        weighted = score * weight_pct / 100
        return f"| {label} | {score:.1f}/10 | {weight_pct}% | {weighted:.2f} |"

    ws_str = f"{weighted_score:.2f}/10" if weighted_score is not None else "N/A"

    report += f"""## 🎯 基金经理最终决策 (FundManager)

### 决策: **{decision.action}** (置信度: {conf_str})

### 评分汇总

| 维度 | 评分 | 权重 | 加权 |
|------|------|------|------|
{_score_row("基本面", f_score, 40)}
{_score_row("技术面", t_score, 30)}
{_score_row("情绪面", s_score, 30)}
| **综合** | **{ws_str}** | | |

"""

    if decision.decision_methodology:
        report += f"""### 决策方法论

{decision.decision_methodology}

"""

    report += f"""### 执行摘要

{decision.summary}

"""

    if decision.bull_case:
        report += f"""### 多头论点

{decision.bull_case}

"""

    if decision.bear_case:
        report += f"""### 空头论点

{decision.bear_case}

"""

    if decision.risk_assessment:
        report += f"""### 风险评估

{decision.risk_assessment}

"""

    # Price targets
    report += """### 价格目标与仓位

| 项目 | 数值 |
|------|------|
"""
    report += f"| 当前价格 | {_fmt_number(decision.current_price)} |\n"
    report += f"| 目标价 | {_fmt_number(decision.target_price)} |\n"
    report += f"| 止损价 | {_fmt_number(decision.stop_loss)} |\n"
    pct_str = f"{decision.position_size_pct:.1%}" if decision.position_size_pct is not None else "N/A"
    shares = decision.position_size_shares or 0
    report += f"| 建议仓位 | {pct_str} |\n"
    report += f"| 建议股数 | {shares} 股 ({shares // 100} 手) |\n"

    if decision.target_price and decision.current_price:
        upside = (decision.target_price - decision.current_price) / decision.current_price * 100
        report += f"| 上涨空间 | {upside:+.1f}% |\n"
    if decision.stop_loss and decision.current_price:
        downside = (decision.stop_loss - decision.current_price) / decision.current_price * 100
        report += f"| 下行风险 | {downside:+.1f}% |\n"

    report += "\n---\n\n"

    # ── Portfolio section
    report += _render_portfolio_section(decision)

    # ── Shared data (market context, quant signals, news) — rendered ONCE
    report += _render_shared_data_section(decision.agent_reports)

    # ── Each agent's analysis (compact: shared data stripped from raw data)
    seen = set()
    for agent_report in decision.agent_reports:
        key = (agent_report.agent_name, agent_report.symbol)
        if key in seen:
            continue
        seen.add(key)
        report += _render_agent(agent_report)

    report += "\n---\n\n*AI多智能体系统生成，仅供参考，不构成投资建议。*\n"
    return report


def save_report(decision: FinalDecision, output_dir: Path) -> Path:
    """Save report to date-based subfolder: output_dir/YYYY-MM-DD/symbol_HHMM.md"""
    date_folder = output_dir / datetime.now().strftime("%Y-%m-%d")
    date_folder.mkdir(parents=True, exist_ok=True)
    filename = f"{decision.symbol}_{datetime.now().strftime('%H%M')}.md"
    path = date_folder / filename
    content = generate_report(decision)
    path.write_text(content, encoding="utf-8")
    return path
