"""Quantitative signal computation — ALL math happens here, not in the LLM.

This module computes:
  - Kelly criterion position sizing
  - Composite signal scoring (weighted multi-factor)
  - Risk-adjusted position sizing
  - Technical signal classification
  - Fundamental valuation signals
  - Portfolio risk decomposition

The LLM agents receive these pre-computed numbers and make DECISIONS,
they do NOT perform calculations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


# ─── Signal Classification ───────────────────────────────────────────


@dataclass
class TechnicalSignal:
    """Pre-computed technical trading signal."""
    trend: str = "neutral"            # bullish / bearish / neutral
    trend_strength: float | None = None  # 0-1 how aligned MAs are
    momentum: str = "neutral"         # positive / negative / neutral
    rsi_zone: str = "neutral"         # overbought / oversold / neutral
    macd_cross: str = "none"          # golden_cross / dead_cross / none
    bollinger_position: str = "mid"   # above_upper / below_lower / mid
    volume_confirmation: bool = False
    kdj_signal: str = "neutral"       # overbought / oversold / golden / dead / neutral
    support_distance_pct: float | None = None
    resistance_distance_pct: float | None = None


@dataclass
class FundamentalSignal:
    """Pre-computed fundamental valuation signal."""
    value_score: float | None = None      # 0-10, None = not enough data
    quality_score: float | None = None
    growth_score: float | None = None
    safety_score: float | None = None
    peg_ratio: float | None = None
    intrinsic_value_estimate: float | None = None
    margin_of_safety_pct: float | None = None


@dataclass
class QuantSignal:
    """Pre-computed quantitative trading parameters."""
    kelly_fraction: float | None = None
    half_kelly: float | None = None
    position_size_pct: float | None = None
    position_size_shares: int | None = None
    expected_return: float | None = None
    risk_reward_ratio: float | None = None
    win_probability: float | None = None
    avg_win_loss_ratio: float | None = None
    composite_score: float | None = None    # 0-10 weighted score
    signal: str = "HOLD"                    # BUY / SELL / HOLD


@dataclass
class RiskSignal:
    """Pre-computed risk assessment."""
    position_risk_pct: float | None = None
    stop_loss_price: float | None = None
    max_loss_amount: float | None = None
    portfolio_var_impact: float | None = None
    concentration_ok: bool = True
    drawdown_ok: bool = True
    liquidity_ok: bool = True
    volatility_ok: bool = True
    risk_approved: bool = True
    veto_reasons: list[str] = field(default_factory=list)


# ─── Technical Signal Computation ────────────────────────────────────


def compute_technical_signal(
    indicators: dict,
    current_price: float | None,
) -> TechnicalSignal:
    """Classify technical indicators into actionable signals.

    Skips any analysis where the underlying indicator is None.
    """
    sig = TechnicalSignal()
    price = current_price or 0

    # Trend strength: how aligned are MAs (5 > 10 > 20 > 60 = perfect bullish)
    mas = [indicators.get(f"ma_{p}") for p in [5, 10, 20, 60]]
    mas = [m for m in mas if m is not None and m > 0]
    if len(mas) >= 3:
        bullish_pairs = sum(1 for i in range(len(mas) - 1) if mas[i] > mas[i + 1])
        bearish_pairs = sum(1 for i in range(len(mas) - 1) if mas[i] < mas[i + 1])
        total_pairs = len(mas) - 1
        if bullish_pairs == total_pairs:
            sig.trend = "bullish"
            sig.trend_strength = 1.0
        elif bearish_pairs == total_pairs:
            sig.trend = "bearish"
            sig.trend_strength = 1.0
        else:
            sig.trend = "neutral"
            sig.trend_strength = max(bullish_pairs, bearish_pairs) / total_pairs

    # RSI zone — only classify if RSI data is available
    rsi = indicators.get("rsi_14")
    if rsi is not None:
        if rsi > 70:
            sig.rsi_zone = "overbought"
        elif rsi < 30:
            sig.rsi_zone = "oversold"
        else:
            sig.rsi_zone = "neutral"

    # MACD cross
    macd_hist = indicators.get("macd_hist")
    if macd_hist is not None:
        if macd_hist > 0:
            sig.momentum = "positive"
            sig.macd_cross = "golden_cross"
        elif macd_hist < 0:
            sig.momentum = "negative"
            sig.macd_cross = "dead_cross"

    # Bollinger position
    bb_upper = indicators.get("bollinger_upper")
    bb_lower = indicators.get("bollinger_lower")
    if bb_upper is not None and price > bb_upper:
        sig.bollinger_position = "above_upper"
    elif bb_lower is not None and bb_lower > 0 and price < bb_lower:
        sig.bollinger_position = "below_lower"

    # KDJ — only classify if data available
    kdj_k = indicators.get("kdj_k")
    kdj_d = indicators.get("kdj_d")
    kdj_j = indicators.get("kdj_j")
    if kdj_j is not None:
        if kdj_j > 100:
            sig.kdj_signal = "overbought"
        elif kdj_j < 0:
            sig.kdj_signal = "oversold"
        elif kdj_k is not None and kdj_d is not None:
            if kdj_k > kdj_d and kdj_k < 30:
                sig.kdj_signal = "golden"
            elif kdj_k < kdj_d and kdj_k > 70:
                sig.kdj_signal = "dead"

    # Support/Resistance distance
    supports = indicators.get("support_levels", [])
    resistances = indicators.get("resistance_levels", [])
    if supports and price > 0:
        sig.support_distance_pct = round((price - supports[0]) / price * 100, 2)
    if resistances and price > 0:
        sig.resistance_distance_pct = round((resistances[0] - price) / price * 100, 2)

    return sig


# ─── Fundamental Signal Computation ──────────────────────────────────


def _latest(val):
    """Extract the latest value from a list or return as-is."""
    if isinstance(val, (list, tuple)) and val:
        return val[0]
    return val


def compute_fundamental_signal(
    financials: dict,
    current_price: float | None,
    market_cap: float | None,
) -> FundamentalSignal:
    """Score fundamentals using Graham + Simons factor model.

    Each sub-score is only computed if the required data is available.
    None = insufficient data to compute that score.
    """
    sig = FundamentalSignal()
    price = current_price or 0

    # ── Value score (Graham: PE, PB, margin of safety) ──
    pe = _latest(financials.get("pe_ratio"))
    pb = _latest(financials.get("pb_ratio"))
    has_value_data = pe is not None or pb is not None
    if has_value_data:
        value_points = 5.0
        if pe is not None and pe > 0:
            if pe < 10:
                value_points += 2.5
            elif pe < 15:
                value_points += 1.5
            elif pe < 25:
                value_points += 0.0
            elif pe < 40:
                value_points -= 1.5
            else:
                value_points -= 2.5
        if pb is not None and pb > 0:
            if pb < 1.0:
                value_points += 1.5
            elif pb < 2.0:
                value_points += 0.5
            elif pb > 5.0:
                value_points -= 1.5
        sig.value_score = max(0.0, min(10.0, value_points))

    # ── Quality score (ROE, margins, cash flow quality) ──
    roe = _latest(financials.get("roe"))
    gross_margin = _latest(financials.get("gross_margin"))
    net_margin = _latest(financials.get("net_margin"))
    ocf = _latest(financials.get("operating_cash_flow"))
    net_profit = _latest(financials.get("net_profit"))

    has_quality_data = any(v is not None for v in [roe, gross_margin, net_margin])
    if has_quality_data:
        quality = 5.0
        if roe is not None:
            if roe > 20:
                quality += 2.0
            elif roe > 15:
                quality += 1.0
            elif roe > 10:
                quality += 0.5
            elif roe < 5:
                quality -= 1.5

        if gross_margin is not None:
            if gross_margin > 40:
                quality += 1.0
            elif gross_margin < 15:
                quality -= 1.0

        # Cash flow quality: OCF should exceed net profit (Simons factor)
        if net_profit is not None and ocf is not None and net_profit > 0:
            if ocf > net_profit:
                quality += 1.0
            elif ocf < net_profit * 0.5:
                quality -= 1.5

        sig.quality_score = max(0.0, min(10.0, quality))

    # ── Growth score ──
    rev_growth = _latest(financials.get("revenue_growth"))
    profit_growth = _latest(financials.get("profit_growth"))
    growth_inputs = [g for g in [rev_growth, profit_growth] if g is not None]
    if growth_inputs:
        growth = 5.0
        for g in growth_inputs:
            if g > 30:
                growth += 1.5
            elif g > 15:
                growth += 0.75
            elif g > 0:
                growth += 0.25
            elif g < -10:
                growth -= 1.5
            elif g < 0:
                growth -= 0.5
        sig.growth_score = max(0.0, min(10.0, growth))

    # ── Safety score (Graham: debt, current ratio) ──
    debt_to_equity = _latest(financials.get("debt_to_equity"))
    if debt_to_equity is not None:
        safety = 5.0
        if debt_to_equity < 0.3:
            safety += 2.0
        elif debt_to_equity < 0.6:
            safety += 1.0
        elif debt_to_equity > 1.5:
            safety -= 2.0
        elif debt_to_equity > 1.0:
            safety -= 1.0
        sig.safety_score = max(0.0, min(10.0, safety))

    # ── PEG ratio ──
    eps_growth_candidates = [g for g in [rev_growth, profit_growth] if g is not None and g > 0]
    eps_growth = max(eps_growth_candidates) if eps_growth_candidates else None
    if pe is not None and pe > 0 and eps_growth is not None and eps_growth > 0:
        sig.peg_ratio = round(pe / eps_growth, 2)

    # ── Intrinsic value estimate (earnings-based, Graham formula) ──
    # Graham: V = EPS × (8.5 + 2g) where g = expected growth rate
    eps = _latest(financials.get("eps"))
    if eps is not None and eps > 0:
        g = min(max(eps_growth or 0, 0), 25)  # cap growth at 25%
        graham_value = eps * (8.5 + 2 * g)
        sig.intrinsic_value_estimate = round(graham_value, 2)
        if price > 0:
            sig.margin_of_safety_pct = round(
                (graham_value - price) / price * 100, 2
            )

    return sig


# ─── Kelly Criterion & Position Sizing ───────────────────────────────


def compute_kelly_criterion(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    cap: float = 0.25,
) -> float:
    """Kelly criterion: f* = (b*p - q) / b where b = avg_win/avg_loss.

    Returns fraction of capital to risk (can be negative = don't bet).
    """
    if avg_loss <= 0 or avg_win <= 0:
        return 0.0
    b = avg_win / avg_loss  # odds ratio
    p = win_rate
    q = 1 - p
    kelly = (b * p - q) / b
    return max(0.0, min(kelly, cap))


def estimate_win_rate_from_signals(
    tech_signal: TechnicalSignal,
    fund_signal: FundamentalSignal,
    risk_metrics: dict,
    hold_period_days: int = 20,
) -> tuple[float, float, float]:
    """Estimate win probability and avg win/loss from pre-computed signals.

    Returns: (win_rate, avg_win_pct, avg_loss_pct)
    """
    # Base win rate from trend + fundamentals
    base = 0.50

    # Trend alignment bonus
    if tech_signal.trend == "bullish":
        base += 0.08
    elif tech_signal.trend == "bearish":
        base -= 0.08

    # RSI extremes
    if tech_signal.rsi_zone == "oversold":
        base += 0.05  # mean reversion tendency
    elif tech_signal.rsi_zone == "overbought":
        base -= 0.05

    # Fundamental quality — only adjust if scores are available
    available_scores = [s for s in [fund_signal.value_score, fund_signal.quality_score]
                        if s is not None]
    if available_scores:
        avg_fund = sum(available_scores) / len(available_scores)
        base += (avg_fund - 5) * 0.02  # +/- 0.10 range

    # Margin of safety
    if fund_signal.margin_of_safety_pct is not None:
        if fund_signal.margin_of_safety_pct > 20:
            base += 0.05
        elif fund_signal.margin_of_safety_pct < -20:
            base -= 0.05

    win_rate = max(0.30, min(0.70, base))

    # Avg win/loss from volatility, scaled by hold period
    vol = risk_metrics.get("volatility_annual") or 0.30
    daily_vol = vol / math.sqrt(245)
    avg_win = daily_vol * hold_period_days * 1.2   # slight optimism
    avg_loss = daily_vol * hold_period_days * 0.8  # stops cut losses shorter

    return win_rate, max(avg_win, 0.01), max(avg_loss, 0.01)


def compute_position_size(
    kelly_fraction: float,
    portfolio_value: float,
    current_price: float | None,
    max_position_pct: float = 0.10,
    lot_size: int = 100,
) -> tuple[float, int]:
    """Compute position size from Kelly fraction.

    Returns: (position_pct, shares)
    """
    # Half-Kelly for safety (Simons principle: never full Kelly)
    half_kelly = kelly_fraction / 2.0
    position_pct = min(half_kelly, max_position_pct)

    if not current_price or current_price <= 0 or portfolio_value <= 0:
        return position_pct, 0

    position_value = portfolio_value * position_pct
    shares = int(position_value / current_price) // lot_size * lot_size

    return position_pct, shares


# ─── Composite Signal Scoring ────────────────────────────────────────


def compute_composite_score(
    fund_signal: FundamentalSignal,
    tech_signal: TechnicalSignal,
    risk_metrics: dict,
    weights: dict | None = None,
    buy_threshold: float = 7.0,
    sell_threshold: float = 3.5,
) -> tuple[float, str]:
    """Compute weighted composite score and derive signal.

    Default weights (Simons-inspired factor model):
      Fundamental: 0.40 (value + quality + safety)
      Technical:   0.30 (trend + momentum)
      Growth:      0.15 (growth trajectory)
      Risk:        0.15 (risk-adjusted return potential)

    Missing components are excluded and weights renormalized.
    Returns: (composite_score 0-10, signal BUY/SELL/HOLD)
    """
    w = weights or {"fundamental": 0.40, "technical": 0.30, "growth": 0.15, "risk": 0.15}

    # Build components that have data
    components: list[tuple[str, float]] = []

    # Fundamental component: average of available sub-scores
    fund_subs = [s for s in [fund_signal.value_score, fund_signal.quality_score,
                              fund_signal.safety_score] if s is not None]
    if fund_subs:
        fund_score = sum(fund_subs) / len(fund_subs)
        components.append(("fundamental", fund_score))

    # Technical component: map signals to score
    tech_score = 5.0
    if tech_signal.trend == "bullish":
        tech_score += 2.0
    elif tech_signal.trend == "bearish":
        tech_score -= 2.0
    if tech_signal.momentum == "positive":
        tech_score += 1.0
    elif tech_signal.momentum == "negative":
        tech_score -= 1.0
    if tech_signal.rsi_zone == "oversold":
        tech_score += 0.5
    elif tech_signal.rsi_zone == "overbought":
        tech_score -= 0.5
    tech_score = max(0.0, min(10.0, tech_score))
    components.append(("technical", tech_score))

    # Growth component — only if available
    if fund_signal.growth_score is not None:
        components.append(("growth", fund_signal.growth_score))

    # Risk component: Sharpe-based
    sharpe = risk_metrics.get("sharpe_ratio")
    if sharpe is not None:
        risk_score = 5.0 + min(max(sharpe, -2), 2) * 2.0  # maps [-2,2] → [1,9]
        risk_score = max(0.0, min(10.0, risk_score))
        components.append(("risk", risk_score))

    if not components:
        return 5.0, "HOLD"

    # Renormalize weights to sum to 1.0 over available components
    total_weight = sum(w.get(name, 0) for name, _ in components)
    if total_weight <= 0:
        return 5.0, "HOLD"

    composite = sum(score * w.get(name, 0) / total_weight for name, score in components)
    composite = round(max(0.0, min(10.0, composite)), 2)

    # Signal derivation
    if composite >= buy_threshold:
        signal = "BUY"
    elif composite <= sell_threshold:
        signal = "SELL"
    else:
        signal = "HOLD"

    return composite, signal


# ─── Risk Assessment (Taleb + Markowitz) ─────────────────────────────


def compute_risk_assessment(
    current_price: float | None,
    atr: float | None,
    risk_metrics: dict,
    portfolio_value: float,
    portfolio_positions: list[dict],
    proposed_position_pct: float,
    risk_limits: dict,
    stop_loss_atr_mult: float = 2.0,
) -> RiskSignal:
    """Pre-compute all risk checks so the Risk Manager AI only interprets.

    Taleb principles:
      - Never risk ruin (max drawdown hard limit)
      - Fat tails exist — VaR underestimates true risk by ~2x
      - Antifragility: small losses OK, catastrophic losses never

    Markowitz principles:
      - Diversification: concentration limits
      - Efficient frontier: risk-adjusted returns
    """
    sig = RiskSignal()
    price = current_price or 0
    pos_pct = proposed_position_pct or 0

    # ── Stop loss: N× ATR below current price (Taleb: cut losses aggressively)
    if price > 0:
        if atr is not None and atr > 0:
            sig.stop_loss_price = round(price - stop_loss_atr_mult * atr, 3)
        else:
            sig.stop_loss_price = round(price * 0.95, 3)  # 5% default

    # ── Position risk
    if price > 0 and sig.stop_loss_price is not None:
        position_value = portfolio_value * pos_pct
        loss_per_share = price - sig.stop_loss_price
        sig.position_risk_pct = round(loss_per_share / price * pos_pct * 100, 2)
        sig.max_loss_amount = round(position_value * (loss_per_share / price), 2)

    # ── Concentration check (Markowitz)
    max_single = risk_limits.get("max_single_position_pct", 0.10)
    if pos_pct > max_single:
        sig.concentration_ok = False
        sig.veto_reasons.append(
            f"持仓集中度超限: {pos_pct:.1%} > {max_single:.1%}"
        )

    # ── Drawdown check (Taleb: never approach ruin)
    max_dd_limit = risk_limits.get("max_drawdown_pct", 0.15)
    current_dd_raw = risk_metrics.get("current_drawdown")
    current_dd = abs(current_dd_raw) if current_dd_raw is not None else 0
    if current_dd > max_dd_limit * 0.8:
        sig.drawdown_ok = False
        sig.veto_reasons.append(
            f"回撤接近上限: 当前回撤 {current_dd:.1%} ≈ 限制 {max_dd_limit:.1%}"
        )

    # ── Volatility check (Taleb: beware fat tails)
    vol = risk_metrics.get("volatility_annual")
    var_95 = risk_metrics.get("value_at_risk_95")
    if vol is not None and vol > 0.60:  # >60% annualized vol = extreme
        sig.volatility_ok = False
        var_str = f"{var_95:.2%}/day" if var_95 is not None else "N/A"
        sig.veto_reasons.append(
            f"波动率极端: 年化波动 {vol:.1%}，VaR95 = {var_str}"
        )

    # ── Taleb fat-tail adjustment: true risk ≈ 2× VaR
    if var_95 is not None and var_95 < 0:
        sig.portfolio_var_impact = round(abs(var_95) * 2 * pos_pct * 100, 2)

    # ── Final verdict
    sig.risk_approved = all([
        sig.concentration_ok, sig.drawdown_ok,
        sig.liquidity_ok, sig.volatility_ok,
    ])
    if not sig.risk_approved:
        # But never fully veto — suggest reduced size instead
        pass

    return sig


# ─── Full Quant Pipeline ─────────────────────────────────────────────


def run_quant_pipeline(
    indicators: dict,
    financials: dict,
    risk_metrics: dict,
    current_price: float | None,
    market_cap: float | None,
    portfolio_value: float,
    portfolio_positions: list[dict],
    risk_limits: dict,
    atr: float | None = None,
    *,
    horizon_weights: dict | None = None,
    kelly_cap: float = 0.25,
    hold_period_days: int = 20,
    stop_loss_atr_mult: float = 2.0,
    buy_threshold: float = 7.0,
    sell_threshold: float = 3.5,
) -> dict:
    """Run the full quantitative pipeline. Returns all pre-computed signals.

    Args:
        horizon_weights: Override composite weights, e.g.
            {"fundamental": 0.15, "technical": 0.45, "growth": 0.05, "risk": 0.35}
        kelly_cap: Max Kelly fraction (default 0.25, short-term may use 0.20)
        hold_period_days: Expected hold days for win/loss estimation
        stop_loss_atr_mult: ATR multiplier for stop loss
        buy_threshold: Composite score >= this → BUY signal
        sell_threshold: Composite score <= this → SELL signal
    """
    # 1. Technical signal classification
    tech_signal = compute_technical_signal(indicators, current_price)

    # 2. Fundamental signal scoring
    fund_signal = compute_fundamental_signal(financials, current_price, market_cap)

    # 3. Composite score with horizon-specific weights
    composite, signal = compute_composite_score(
        fund_signal, tech_signal, risk_metrics,
        weights=horizon_weights,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
    )

    # 4. Kelly criterion with horizon-adjusted hold period
    win_rate, avg_win, avg_loss = estimate_win_rate_from_signals(
        tech_signal, fund_signal, risk_metrics, hold_period_days=hold_period_days
    )
    kelly = compute_kelly_criterion(win_rate, avg_win, avg_loss, cap=kelly_cap)
    pos_pct, pos_shares = compute_position_size(
        kelly, portfolio_value, current_price,
        max_position_pct=risk_limits.get("max_single_position_pct", 0.10),
    )

    # 5. Risk assessment with horizon-specific stop loss
    risk_signal = compute_risk_assessment(
        current_price, atr, risk_metrics,
        portfolio_value, portfolio_positions,
        pos_pct, risk_limits,
        stop_loss_atr_mult=stop_loss_atr_mult,
    )

    # 6. Build quant signal
    quant = QuantSignal(
        kelly_fraction=round(kelly, 4),
        half_kelly=round(kelly / 2, 4),
        position_size_pct=pos_pct,
        position_size_shares=pos_shares,
        expected_return=round(win_rate * avg_win - (1 - win_rate) * avg_loss, 4),
        risk_reward_ratio=round(avg_win / (avg_loss + 1e-10), 2),
        win_probability=round(win_rate, 3),
        avg_win_loss_ratio=round(avg_win / (avg_loss + 1e-10), 2),
        composite_score=composite,
        signal=signal,
    )

    # Convert dataclasses to dicts for JSON serialization
    return {
        "technical_signal": _dc_to_dict(tech_signal),
        "fundamental_signal": _dc_to_dict(fund_signal),
        "quant_signal": _dc_to_dict(quant),
        "risk_signal": _dc_to_dict(risk_signal),
    }


def _dc_to_dict(dc) -> dict:
    """Convert a dataclass to dict."""
    from dataclasses import asdict
    return asdict(dc)


# ─── None-Value Annotation ───────────────────────────────────────────


# Maps each signal field to (condition_description, required_inputs_description)
_FUNDAMENTAL_NULL_REASONS = {
    "value_score": "PE and PB ratios both unavailable (company may not have reported earnings yet)",
    "quality_score": "ROE, gross margin, net margin, and cash flow data all unavailable",
    "growth_score": "Revenue growth and profit growth data both unavailable",
    "safety_score": "Debt-to-equity ratio data unavailable",
    "peg_ratio": "Requires positive PE and positive earnings growth — one or both missing",
    "intrinsic_value_estimate": "Graham formula requires positive EPS — company has negative or missing EPS",
    "margin_of_safety_pct": "Cannot compute without intrinsic value estimate (see above)",
}

_TECHNICAL_NULL_REASONS = {
    "support_distance_pct": "No support levels identified from recent price history",
    "resistance_distance_pct": "No resistance levels identified from recent price history",
}

_RISK_NULL_REASONS = {
    "stop_loss_price": "ATR unavailable — insufficient price history to compute volatility-based stop",
    "max_loss_amount": "Depends on stop_loss_price which is unavailable",
    "position_risk_pct": "Cannot compute without stop_loss_price",
    "portfolio_var_impact": "VaR not available from risk metrics — insufficient return history",
}


def annotate_null_fields(signals: dict) -> dict:
    """Add _note annotations for every null field in quant signal dicts.

    For each signal category, if a field is None, adds a sibling field
    '{field_name}_note' explaining WHY it's null. This prevents the LLM
    from misinterpreting None as "system error" vs. "metric not applicable".

    Args:
        signals: The output of run_quant_pipeline() — dict of signal dicts.

    Returns:
        The same dict, mutated in place with _note fields added.
    """
    reason_maps = {
        "fundamental_signal": _FUNDAMENTAL_NULL_REASONS,
        "technical_signal": _TECHNICAL_NULL_REASONS,
        "risk_signal": _RISK_NULL_REASONS,
    }

    for signal_key, reasons in reason_maps.items():
        sig = signals.get(signal_key, {})
        for field, reason in reasons.items():
            if field in sig and sig[field] is None:
                sig[f"{field}_note"] = reason

    return signals
