"""Tests for agent data gathering and report models."""

import pytest

from stock_agents.models.signals import AgentReport, DebateReport, FinalDecision


class TestAgentReport:
    def test_default_values(self):
        report = AgentReport(agent_name="test", agent_role="tester", symbol="000001")
        assert report.signal == "HOLD"
        assert report.score == 5.0
        assert report.confidence == 0.5

    def test_custom_values(self):
        report = AgentReport(
            agent_name="BullResearcher",
            agent_role="多头研究员",
            symbol="603993",
            signal="BUY",
            score=8.5,
            confidence=0.85,
            reasoning="Strong growth potential",
            key_factors=["Revenue up 50%", "High dividend"],
            risks=["Commodity volatility"],
        )
        assert report.signal == "BUY"
        assert len(report.key_factors) == 2
        assert len(report.risks) == 1


class TestDebateReport:
    def test_net_conviction(self):
        debate = DebateReport(
            symbol="603993",
            bull_score=8.5,
            bear_score=3.5,
            net_conviction=0.5,
        )
        expected = (8.5 - 3.5) / 10.0
        assert abs(debate.net_conviction - expected) < 0.01

    def test_bearish_conviction(self):
        debate = DebateReport(
            symbol="603993",
            bull_score=3.0,
            bear_score=8.0,
            net_conviction=-0.5,
        )
        assert debate.net_conviction < 0


class TestFinalDecision:
    def test_default_action(self):
        decision = FinalDecision(symbol="603993")
        assert decision.action == "HOLD"
        assert decision.confidence == 0.5

    def test_portfolio_fields(self):
        decision = FinalDecision(
            symbol="603993",
            portfolio_snapshot={"cash": 35000, "total_value": 56000},
            trade_history=[{"action": "buy", "symbol": "603993"}],
        )
        assert decision.portfolio_snapshot["cash"] == 35000
        assert len(decision.trade_history) == 1

    def test_position_sizing(self):
        decision = FinalDecision(
            symbol="603993",
            position_size_pct=0.37,
            position_size_shares=1100,
        )
        assert decision.position_size_pct > 0
        assert decision.position_size_shares > 0
        assert decision.position_size_shares % 100 == 0


class TestReportGenerator:
    def test_generate_report(self):
        from stock_agents.output.report_generator import generate_report
        decision = FinalDecision(
            symbol="603993",
            name="洛阳钼业",
            action="HOLD",
            confidence=1.0,
            current_price=19.14,
            fundamental_score=5.0,
            technical_score=5.0,
            sentiment_score=8.5,
            summary="Test summary",
            position_size_pct=0.37,
            position_size_shares=1100,
        )
        report = generate_report(decision)
        assert "603993" in report
        assert "洛阳钼业" in report
        assert "HOLD" in report
        assert "37.0%" in report  # position size

    def test_report_contains_all_sections(self):
        from stock_agents.output.report_generator import generate_report
        agent_reports = [
            AgentReport(agent_name="fundamental", agent_role="analyst", symbol="603993", signal="BUY", score=7.5),
            AgentReport(agent_name="technical", agent_role="analyst", symbol="603993", signal="HOLD", score=5.0),
        ]
        decision = FinalDecision(
            symbol="603993", name="Test Stock",
            agent_reports=agent_reports,
            summary="Test",
            fundamental_score=7.5, technical_score=5.0, sentiment_score=6.0,
        )
        report = generate_report(decision)
        assert "分析报告" in report
        assert "基金经理最终决策" in report
        assert "价格目标与仓位" in report
