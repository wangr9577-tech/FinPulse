"""Pydantic 数据模型：公告、分析结果、报告数据。"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class Announcement(BaseModel):
    """一条公告（沪深两所统一结构）。"""
    stock_code: str
    stock_name: str = ""
    title: str
    category: str = ""
    pdf_url: str = ""
    exchange: str  # "SSE" | "SZSE"
    publish_time: Optional[datetime] = None
    announce_date: date
    full_text: str = ""  # pypdf 提取的正文（分析用）


class AnalysisResult(BaseModel):
    """DeepSeek 影响分析结果。"""
    sentiment: str = Field(pattern="^(利好|利空|中性)$")
    level: str = Field(pattern="^(高|中|低)$")
    sectors: list[str] = []
    reason: str = ""
    key_points: list[str] = []
    full_text_analyzed: bool = False
    degraded: bool = True  # True=未全文解析（仅标题或解析失败降级）


class ReportRow(BaseModel):
    """报告中一行（公告 + 分析）。"""
    announcement: Announcement
    analysis: AnalysisResult


class ReportData(BaseModel):
    """报告所需的全部数据。"""
    date: date
    total: int
    sentiment_counts: dict[str, int]
    high_level: list[ReportRow]
    medium_level: list[ReportRow] = []   # 利好·中（仅利好优先模式使用）
    low_level: list[ReportRow] = []      # 利好·低
    level_counts: dict[str, int] = {}    # 利好程度分布 {"高":x,"中":y,"低":z}
    full_list: list[ReportRow]
    degraded_rows: list[ReportRow]
    tiered_mode: bool
    tiered_reason: str = ""
    sources_note: str = ""  # 数据源异常提示（如某交易所爬取失败导致报告不完整）


class SectorQuote(BaseModel):
    """一个源的一条板块行情。"""
    board_name: str
    board_type: str = Field(pattern="^(industry|concept)$")
    source: str = Field(pattern="^(sina|eastmoney|ths)$")
    pct_change: float = 0.0       # 涨幅 %
    net_inflow: float = 0.0       # 资金净流入（元）
    up_count: int = 0             # 板块内上涨家数（东财 f104，作涨停家数代理）
    float_market_cap: float = 0.0   # 流通市值（元），东财 f21
    total_count: int = 0            # 板块成分总家数（涨+跌+平）
    leader_stocks: list[str] = [] # 领涨股 ["代码 名称", ...]


class SectorAnalysis(BaseModel):
    """融合评分后的板块结果。"""
    board_name: str
    board_type: str = Field(pattern="^(industry|concept)$")
    score: float = 0.0
    grade: str = Field(default="弱", pattern="^(强|中|弱)$")
    pct_change: float = 0.0
    net_inflow: float = 0.0
    up_count: int = 0
    float_market_cap: float = 0.0   # 流通市值（元），东财 f21
    total_count: int = 0            # 板块成分总家数（涨+跌+平）
    leader_stocks: list[str] = []
    comment: str = ""             # DeepSeek 一句话点评
    research_score: float = 50.0   # 研报维度得分 0-100，缺研报记 50（中性）
    research_note: str = ""        # 券商观点摘要（如"2篇看好"），空串=无研报


class ResearchReport(BaseModel):
    """一条个股研报元数据（reportapi 实测字段）。"""
    stock_code: str
    stock_name: str = ""
    title: str = ""
    org_name: str = ""
    researcher: str = ""
    publish_date: str = ""
    rating: str = ""            # emRatingName：买入/增持/中性/减持/卖出
    last_rating: str = ""       # 上次评级
    rating_change: int = 0      # 评级变化（>0 上调）
    aim_price_t: float = 0.0    # 目标价上限（缺失为 0）
    aim_price_l: float = 0.0    # 目标价下限
    eps_forecast: float = 0.0   # 当年 EPS 预测
    pdf_url: str = ""           # pdf.dfcfw.com 直链
    source: str = "eastmoney"


class IndustryReport(BaseModel):
    """一条行业研报元数据（reportapi qType=1 实测字段）。"""
    industry_name: str = ""     # industryName：东财行业名（如"化学制药"）
    title: str = ""
    org_name: str = ""
    researcher: str = ""
    publish_date: str = ""
    rating: str = ""            # sRatingName：券商行业评级（看好/推荐/中性/回避）
    em_rating: str = ""         # emRatingName：个股评级词表，作 fallback
    pdf_url: str = ""
    source: str = "eastmoney"


class ReportInsight(BaseModel):
    """一篇重点研报的 DeepSeek 观点（PDF 正文提取）。"""
    report: ResearchReport
    summary: str = ""
    highlights: list[str] = []
    risks: list[str] = []
    target_basis: str = ""
    degraded: bool = False


class StockCandidate(BaseModel):
    """打分后的候选股。"""
    stock_code: str
    stock_name: str = ""
    score: float = 0.0
    ann_level: str = ""
    rating: str = ""
    target_upside: float = 0.0   # 目标价空间 %
    source_type: str = Field(default="交集", pattern="^(交集|研报单边)$")
    reasons: list[str] = []


class StockPick(BaseModel):
    """最终推荐（1 支）。"""
    stock_code: str
    stock_name: str = ""
    reason: str = ""
    ann_brief: str = ""
    research_brief: str = ""
    target_upside: float = 0.0
    risk_note: str = ""
    ann_links: list[str] = []          # 该股当日利好公告 pdf_url（去重保序）
    reports: list[ReportInsight] = []  # 该股当日全部买入/增持研报（含完整观点）


class StockPicks(BaseModel):
    """当日选股推荐集合。"""
    date: date
    picks: list[StockPick] = []
    note: str = ""
    degraded: bool = False


class ForecastRow(BaseModel):
    """一条业绩预告（东财 datacenter-web RPT_PUBLIC_OP_NEWPREDICT）。"""
    stock_code: str
    stock_name: str = ""
    forecast_type: str = ""               # 预增/预减/略增/略减/扭亏/续盈/续亏/首亏/不确定
    change_lower: Optional[float] = None  # 净利润同比变动幅度下限 %
    change_upper: Optional[float] = None  # 净利润同比变动幅度上限 %
    content: str = ""                     # 预告内容原文


class DailyReportData(BaseModel):
    """整合报告数据：公告部分 + 板块部分。"""
    date: date
    announcements: "ReportData | None" = None
    sectors_strong: list[SectorAnalysis] = []
    sectors_medium: list[SectorAnalysis] = []
    stock_picks: "StockPicks | None" = None   # 新增：每日选股推荐（可选）
    forecasts: list["ForecastRow"] = []   # 当日业绩预告
