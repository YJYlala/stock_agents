"""Investment horizon configuration — SHORT / MID / LONG term teams.

Each horizon defines:
  - Composite score weights (which factors matter most)
  - Decision thresholds (when to BUY/SELL)
  - Risk parameters (tighter for short, wider for long)
  - Agent emphasis (prompt preambles that shift agent focus)
  - Kelly aggressiveness
  - Hold period assumptions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Horizon(str, Enum):
    SHORT = "short"   # 1 month or less
    MID = "mid"       # 1-6 months
    LONG = "long"     # 6+ months


@dataclass(frozen=True)
class HorizonConfig:
    """All parameters that differ per investment horizon."""
    horizon: Horizon
    label: str
    label_cn: str
    hold_period_days: int        # expected hold period for return calculations
    description: str

    # ── Composite score weights (must sum to 1.0) ──
    weight_fundamental: float
    weight_technical: float
    weight_growth: float
    weight_risk: float

    # ── Decision thresholds ──
    buy_threshold: float         # composite score >= this → BUY candidate
    strong_buy_threshold: float  # composite score >= this AND all agree → STRONG BUY
    sell_threshold: float        # composite score <= this → SELL candidate
    min_buy_votes: int           # minimum BUY votes from core analysts

    # ── Kelly & position sizing ──
    kelly_fraction_cap: float    # max Kelly fraction (short=aggressive, long=conservative)
    max_position_pct: float      # max single position %
    min_risk_reward: float       # minimum risk/reward ratio to consider

    # ── Risk parameters ──
    stop_loss_atr_mult: float    # ATR multiplier for stop loss (tight for short, wide for long)
    max_drawdown_pct: float      # horizon-specific drawdown tolerance

    # ── Agent prompt preambles (injected before the base prompt) ──
    fundamental_preamble: str = ""
    technical_preamble: str = ""
    sentiment_preamble: str = ""
    bull_preamble: str = ""
    bear_preamble: str = ""
    quant_preamble: str = ""
    risk_preamble: str = ""
    fund_manager_preamble: str = ""


# ─── Short-Term Configuration (≤1 month) ─────────────────────────────

SHORT_TERM = HorizonConfig(
    horizon=Horizon.SHORT,
    label="Short-Term",
    label_cn="短线",
    hold_period_days=20,
    description="1个月以内的短线交易，重点关注技术面、动量和市场情绪",

    # Technical & sentiment dominate; fundamentals matter less in short term
    weight_fundamental=0.15,
    weight_technical=0.45,
    weight_growth=0.05,
    weight_risk=0.35,

    # Lower thresholds — more willing to act on momentum
    buy_threshold=6.5,
    strong_buy_threshold=7.5,
    sell_threshold=4.0,
    min_buy_votes=2,

    # More aggressive Kelly, but smaller max position
    kelly_fraction_cap=0.20,
    max_position_pct=0.08,
    min_risk_reward=1.5,

    # Tight stops, lower drawdown tolerance
    stop_loss_atr_mult=1.5,
    max_drawdown_pct=0.08,

    # Agent preambles — shift focus for short-term
    fundamental_preamble=(
        "【短线视角】你只关注未来1个月内会影响股价的基本面因素。"
        "忽略长期增长故事——只看：即将发布的财报是否超预期？"
        "近期是否有重大资产重组、定增、回购等事件驱动？"
        "当前估值在短期交易区间中处于什么位置？\n\n"
    ),
    technical_preamble=(
        "【短线视角】你是短线交易的核心决策者。"
        "重点关注：5日/10日均线趋势、MACD金叉死叉、RSI超买超卖、"
        "KDJ金叉、布林带位置、成交量放大/萎缩。"
        "你的时间框架是1-20个交易日，关注日线级别信号。"
        "入场点位和止损必须精确到分。\n\n"
    ),
    sentiment_preamble=(
        "【短线视角】短线情绪是最重要的驱动力。"
        "关注：今日/本周涨停板数量和板块轮动、龙虎榜游资动向、"
        "融资融券余额变化、北向资金当日流向、"
        "社交媒体热度（股吧、雪球讨论量激增=短期催化）。"
        "一条重磅新闻可以在1-3天内改变股价走势。\n\n"
    ),
    bull_preamble=(
        "【短线多头】构建1个月内股价上涨的案例。"
        "聚焦：技术突破信号、短期催化剂（财报、政策、事件）、"
        "资金面支撑（主力资金流入、融资买入增加）。\n\n"
    ),
    bear_preamble=(
        "【短线空头】识别1个月内的下跌风险。"
        "聚焦：技术破位信号、获利盘抛压、解禁潮、"
        "短期利空消息、资金面撤退信号。\n\n"
    ),
    quant_preamble=(
        "【短线量化】你的持仓周期是1-20个交易日。"
        "Kelly比率使用短期波动率（20日）计算。"
        "T+1限制意味着必须为次日开盘跳空留出安全边际。"
        "仓位不超过总资金的8%——短线纪律严明。\n\n"
    ),
    risk_preamble=(
        "【短线风控】止损必须严格执行（1.5倍ATR）。"
        "单笔最大亏损不超过总资金的1%。"
        "如果大盘当日跌幅>2%或个股触及跌停，立即进入保护模式。"
        "短线交易容错率极低——宁可错过，不可做错。\n\n"
    ),
    fund_manager_preamble=(
        "【短线决策】你是短线交易团队的决策者。\n"
        "核心原则：技术面权重45%，风险权重35%，基本面仅15%。\n"
        "决策速度要快，止损要坚决。\n"
        "如果技术面和情绪面不一致，选择观望（HOLD）。\n\n"
    ),
)


# ─── Mid-Term Configuration (1-6 months) ─────────────────────────────

MID_TERM = HorizonConfig(
    horizon=Horizon.MID,
    label="Mid-Term",
    label_cn="中线",
    hold_period_days=90,
    description="1-6个月的波段操作，平衡基本面催化与技术面择时",

    # Balanced weights — the default team
    weight_fundamental=0.35,
    weight_technical=0.25,
    weight_growth=0.20,
    weight_risk=0.20,

    # Standard thresholds
    buy_threshold=7.0,
    strong_buy_threshold=8.0,
    sell_threshold=3.5,
    min_buy_votes=2,

    # Moderate Kelly
    kelly_fraction_cap=0.25,
    max_position_pct=0.10,
    min_risk_reward=2.0,

    # Standard stops
    stop_loss_atr_mult=2.0,
    max_drawdown_pct=0.15,

    # Agent preambles — balanced perspective
    fundamental_preamble=(
        "【中线视角】你关注未来1-6个月的基本面演变。"
        "重点：本季度和下季度业绩预期、行业景气度拐点、"
        "政策催化（产业政策、财政刺激、货币宽松）。"
        "Graham的安全边际仍然重要——但催化剂的时间点同样关键。\n\n"
    ),
    technical_preamble=(
        "【中线视角】你关注周线级别的趋势和关键位置。"
        "重点：20日/60日均线方向和交叉、周MACD趋势、"
        "月度支撑/阻力位、成交量趋势（量价配合）。"
        "入场时机服务于基本面判断——技术面决定'何时'而非'是否'。\n\n"
    ),
    sentiment_preamble=(
        "【中线视角】你是Dalio的宏观叙事分析师。"
        "关注：行业政策周期（支持期/整顿期/常态化）、"
        "机构持仓变化（公募基金季报、社保基金动向）、"
        "分析师评级调整趋势、行业比较中的相对估值。\n\n"
    ),
    bull_preamble=(
        "【中线多头】构建1-6个月内股价上涨的完整投资逻辑。"
        "需要：明确的催化剂时间线、估值提升空间、"
        "业绩改善路径、行业β和个股α的区分。\n\n"
    ),
    bear_preamble=(
        "【中线空头】识别1-6个月内的核心风险。"
        "关注：业绩不及预期的可能性、估值透支程度、"
        "行业竞争加剧、政策转向风险、宏观逆风。\n\n"
    ),
    quant_preamble=(
        "【中线量化】持仓周期60-120个交易日。"
        "Kelly比率使用中期波动率（60日）。"
        "仓位上限10%——允许足够的时间让投资逻辑发酵。"
        "关注风险回报比≥2:1。\n\n"
    ),
    risk_preamble=(
        "【中线风控】止损设置2倍ATR，给予波动空间。"
        "关注行业集中度——同行业持仓不超过30%。"
        "如果投资逻辑被证伪（如业绩大幅低于预期），无论浮盈浮亏都应离场。\n\n"
    ),
    fund_manager_preamble=(
        "【中线决策】你是波段投资团队的决策者。\n"
        "核心原则：基本面35%、技术面25%、增长20%、风险20%。\n"
        "投资需要明确的催化剂和合理的估值支撑。\n"
        "使用预计算的量化信号作为决策基准。\n\n"
    ),
)


# ─── Long-Term Configuration (6+ months) ─────────────────────────────

LONG_TERM = HorizonConfig(
    horizon=Horizon.LONG,
    label="Long-Term",
    label_cn="长线",
    hold_period_days=365,
    description="6个月以上的价值投资，重点关注企业质量和安全边际",

    # Fundamentals dominate; technical is minor (entry timing only)
    weight_fundamental=0.50,
    weight_technical=0.10,
    weight_growth=0.25,
    weight_risk=0.15,

    # Higher thresholds — only buy truly undervalued quality companies
    buy_threshold=7.5,
    strong_buy_threshold=8.5,
    sell_threshold=3.0,
    min_buy_votes=2,

    # Conservative Kelly, but larger max position for high-conviction
    kelly_fraction_cap=0.15,
    max_position_pct=0.15,
    min_risk_reward=3.0,

    # Wide stops — give the thesis time to play out
    stop_loss_atr_mult=3.0,
    max_drawdown_pct=0.20,

    # Agent preambles — deep value / Buffett perspective
    fundamental_preamble=(
        "【长线视角】你是Benjamin Graham和Warren Buffett的忠实信徒。"
        "只问三个问题：\n"
        "1. 这家公司有持久的竞争优势（护城河）吗？\n"
        "2. 管理层是否诚实且能干？\n"
        "3. 当前价格是否提供足够的安全边际（至少20%）？\n"
        "如果三个问题中任何一个答案是否定的，得分不应超过6分。\n"
        "忽略短期波动——关注3-5年的企业价值创造能力。\n\n"
    ),
    technical_preamble=(
        "【长线视角】技术面对长线投资仅作为入场时机参考。"
        "你只需要回答：当前是否在长期趋势的合理买入区间？"
        "关注：120日/250日均线位置、月线级别支撑、"
        "历史估值底部区间。不要被日线噪音干扰。\n\n"
    ),
    sentiment_preamble=(
        "【长线视角】Dalio的长周期宏观框架。"
        "关注：经济周期位置（复苏/过热/滞胀/衰退）、"
        "产业生命周期（成长期/成熟期/衰退期）、"
        "人口结构和消费趋势、技术变革（AI、新能源、生物科技）。"
        "短期新闻噪音对长线投资影响有限——除非它改变了行业格局。\n\n"
    ),
    bull_preamble=(
        "【长线多头】构建3-5年企业价值增长的投资论文。"
        "需要论证：护城河的持久性、增长的可持续性、"
        "管理层资本配置能力、行业长期增长空间。"
        "最好的长线投资是：'好公司 + 合理价格'。\n\n"
    ),
    bear_preamble=(
        "【长线空头】Taleb的长期脆弱性检测。"
        "这家公司能否活过下一次经济危机？"
        "关注：资产负债表脆弱性、商业模式被颠覆的风险、"
        "行业是否面临长期结构性衰退、管理层是否有'帝国建造'倾向。"
        "一家看似优秀的公司可能隐藏着致命弱点。\n\n"
    ),
    quant_preamble=(
        "【长线量化】持仓周期250+个交易日。"
        "Kelly比率保守（上限15%），但允许更大单一仓位（15%）因为高确信度。"
        "风险回报比要求≥3:1——长线投资必须有足够的安全边际来补偿时间成本。"
        "关注年化收益率而非短期波动。\n\n"
    ),
    risk_preamble=(
        "【长线风控】止损设置3倍ATR——给予充分的波动空间。"
        "长线风控的核心不是止损，而是：\n"
        "1. 投资逻辑是否仍然成立？\n"
        "2. 企业基本面是否恶化？\n"
        "3. 买入时的安全边际是否已被消耗？\n"
        "如果基本面恶化但股价未跌，同样应该减仓。\n\n"
    ),
    fund_manager_preamble=(
        "【长线决策】你是价值投资团队的决策者。\n"
        "核心原则：基本面50%、增长25%、风险15%、技术面仅10%。\n"
        "只买入有安全边际的优质企业。\n"
        "宁可持有现金等待机会，也不在高估值时入场。\n"
        "如果安全边际不足，即使其他指标优秀，也应HOLD。\n\n"
    ),
)


# ── Lookup ────────────────────────────────────────────────────────────

HORIZON_CONFIGS: dict[Horizon, HorizonConfig] = {
    Horizon.SHORT: SHORT_TERM,
    Horizon.MID: MID_TERM,
    Horizon.LONG: LONG_TERM,
}

ALL_HORIZONS = [Horizon.SHORT, Horizon.MID, Horizon.LONG]


def get_horizon_config(horizon: Horizon | str) -> HorizonConfig:
    """Get config for a specific horizon."""
    if isinstance(horizon, str):
        horizon = Horizon(horizon)
    return HORIZON_CONFIGS[horizon]
