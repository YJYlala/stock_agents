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


def _render_agent(report: AgentReport) -> str:
    """Render one agent's complete analysis."""
    signal_icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(report.signal, "⚪")

    factors = "\n".join(f"- {f}" for f in report.key_factors) if report.key_factors else "N/A"
    risks = "\n".join(f"- {r}" for r in report.risks) if report.risks else "N/A"

    return f"""## {signal_icon} {report.agent_name} ({report.agent_role})

**信号: {report.signal} | 评分: {report.score:.1f}/10 | 置信度: {report.confidence:.0%}**

{report.reasoning}

**关键因素:**
{factors}

**风险因素:**
{risks}

<details>
<summary>原始数据（点击展开）</summary>

{_render_data_section(report.data_used)}

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


def generate_report(decision: FinalDecision) -> str:
    """Generate a comprehensive Markdown report with all agent data."""
    weighted_score = (
        decision.fundamental_score * 0.40
        + decision.technical_score * 0.30
        + decision.sentiment_score * 0.30
    )

    # ── Header
    model_label = decision.llm_model or "未知模型"
    report = f"""# {decision.name} ({decision.symbol}) 分析报告

> 生成时间: {decision.timestamp.strftime("%Y-%m-%d %H:%M")} | 模型: {model_label}

---

"""

    # ── Portfolio section
    report += _render_portfolio_section(decision)

    # ── Each agent's full analysis
    seen = set()
    for agent_report in decision.agent_reports:
        key = (agent_report.agent_name, agent_report.symbol)
        if key in seen:
            continue
        seen.add(key)
        report += _render_agent(agent_report)

    # ── Bull vs Bear debate
    if decision.debate_report:
        d = decision.debate_report
        report += f"""## 多空辩论

| 方向 | 评分 |
|------|------|
| 多头 | {d.bull_score:.1f}/10 |
| 空头 | {d.bear_score:.1f}/10 |
| 净信念 | {d.net_conviction:+.2f} |

**多头论点:** {d.bull_thesis}

**空头论点:** {d.bear_thesis}

---

"""

    # ── Fund Manager final decision
    report += f"""## 基金经理最终决策 (FundManager)

### 决策: **{decision.action}** (置信度: {decision.confidence:.0%})

### 评分汇总

| 维度 | 评分 | 权重 | 加权 |
|------|------|------|------|
| 基本面 | {decision.fundamental_score:.1f}/10 | 40% | {decision.fundamental_score * 0.40:.2f} |
| 技术面 | {decision.technical_score:.1f}/10 | 30% | {decision.technical_score * 0.30:.2f} |
| 情绪面 | {decision.sentiment_score:.1f}/10 | 30% | {decision.sentiment_score * 0.30:.2f} |
| **综合** | **{weighted_score:.2f}/10** | | |

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
    report += f"| 建议仓位 | {decision.position_size_pct:.1%} |\n"
    report += f"| 建议股数 | {decision.position_size_shares} 股 ({decision.position_size_shares // 100} 手) |\n"

    if decision.target_price and decision.current_price:
        upside = (decision.target_price - decision.current_price) / decision.current_price * 100
        report += f"| 上涨空间 | {upside:+.1f}% |\n"
    if decision.stop_loss and decision.current_price:
        downside = (decision.stop_loss - decision.current_price) / decision.current_price * 100
        report += f"| 下行风险 | {downside:+.1f}% |\n"

    report += "\n---\n\n*AI多智能体系统生成，仅供参考，不构成投资建议。*\n"
    return report


def save_report(decision: FinalDecision, output_dir: Path) -> Path:
    """Save report to file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{decision.symbol}_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    path = output_dir / filename
    content = generate_report(decision)
    path.write_text(content, encoding="utf-8")
    return path
