"""两源（东财+新浪）融合 + 量化评分 + 强/中/弱分级。

融合：按 board_type + 归一化板块名对齐各源，仅保留出现在 ≥2 个不同源的板块（交集）。
评分：涨幅 40% / 资金净流入率（净流入÷流通市值）40% / 上涨占比（上涨家数÷总家数）20%
    （权重可配置），各指标 min-max 归一化到 [0,100]；某指标当日全相等（max==min）时
    该指标全体记 50 分中值。
分级：score ≥ 强阈值 → 强；≥ 中阈值 → 中；否则 → 弱。
"""
import unicodedata
from collections import defaultdict

from app.stock_daily.config import settings
from app.stock_daily.models import SectorAnalysis, SectorQuote


def normalize_board_name(name: str) -> str:
    """归一化板块名用于跨源对齐：全角→半角、去空白、统一小写。"""
    return unicodedata.normalize("NFKC", name).replace(" ", "").lower()


def _group_by_board(quotes: list[SectorQuote]) -> dict[tuple[str, str], list[SectorQuote]]:
    """按 (board_type, 归一化名) 聚合各源 quote（保持首次出现顺序）。"""
    groups: dict[tuple[str, str], list[SectorQuote]] = defaultdict(list)
    for q in quotes:
        groups[(q.board_type, normalize_board_name(q.board_name))].append(q)
    return groups


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _merge_group(quotes: list[SectorQuote]) -> SectorAnalysis:
    """把同板块多源 quote 融合为一条：指标取有值来源平均，领涨股取并集。"""
    pct = _average([q.pct_change for q in quotes])
    inflow = _average([q.net_inflow for q in quotes if q.net_inflow != 0])
    up = int(round(_average([q.up_count for q in quotes if q.up_count != 0])))
    mcap = _average([q.float_market_cap for q in quotes if q.float_market_cap != 0])
    total = int(round(_average([q.total_count for q in quotes if q.total_count != 0])))
    leaders: list[str] = []
    for q in quotes:
        for stock in q.leader_stocks:
            if stock and stock not in leaders:
                leaders.append(stock)
    first = quotes[0]
    return SectorAnalysis(
        board_name=first.board_name, board_type=first.board_type,
        pct_change=pct, net_inflow=inflow, up_count=up,
        float_market_cap=mcap, total_count=total,
        leader_stocks=leaders[:2],
    )


def merge_boards(quotes: list[SectorQuote], primary_source: str = "eastmoney") -> list[SectorAnalysis]:
    """聚合为待评分板块，主源优先。

    实测（2026-08-07）：东财（细分主题，行业 496/概念 504）与新浪（证监会大类，
    各 84）板块体系不对齐，名称交集≈0——交集策略会把东财数据全部过滤掉。
    故改为：以东财（字段最全：涨幅/资金/上涨家数/领涨股）为主源，板块全量保留；
    其他源同名板块并入（领涨股并集、涨幅平均）。主源整体失败时由 analyze 降级为新浪。
    """
    groups = _group_by_board(quotes)
    merged: list[SectorAnalysis] = []
    for quotes_list in groups.values():
        primary = [q for q in quotes_list if q.source == primary_source]
        if not primary:
            continue  # 主源模式：无主源的板块（纯新浪）丢弃，避免缺资金/家数污染评分
        others = [q for q in quotes_list if q.source != primary_source]
        merged.append(_merge_group(primary + others))
    return merged


def _minmax_norm(values: list[float]) -> dict[int, float]:
    """min-max 归一化到 [0,100]；全相等时全体记 50（避免除零与全零）。"""
    vmin, vmax = min(values), max(values)
    if vmax == vmin:
        return {i: 50.0 for i in range(len(values))}
    span = vmax - vmin
    return {i: (v - vmin) / span * 100.0 for i, v in enumerate(values)}


def score_boards(
    boards: list[SectorAnalysis],
    research_scores: dict[str, tuple[float, str]] | None = None,
) -> list[SectorAnalysis]:
    """对一批板块按三指标归一化加权评分，叠加研报维度加成，写入 score 并分级。

    research_scores: {归一化板块名: (研报分 0-100, 观点摘要)}，缺研报记 (50, "")，
    加成 = (研报分 - 50) * SECTOR_RESEARCH_WEIGHT（看多加分/看空减分/无研报不变）。
    """
    if not boards:
        return boards
    research_scores = research_scores or {}
    np_ = _minmax_norm([b.pct_change for b in boards])
    ni = _minmax_norm([b.net_inflow / b.float_market_cap if b.float_market_cap > 0 else 0.0
                       for b in boards])
    nu = _minmax_norm([b.up_count / b.total_count if b.total_count > 0 else 0.0
                       for b in boards])
    for i, b in enumerate(boards):
        rs, note = research_scores.get(normalize_board_name(b.board_name), (50.0, ""))
        b.research_score = rs
        b.research_note = note
        base = (np_[i] * settings.SECTOR_PCT_WEIGHT
                + ni[i] * settings.SECTOR_INFLOW_WEIGHT
                + nu[i] * settings.SECTOR_UPCOUNT_WEIGHT)
        b.score = max(0.0, min(100.0, base + (rs - 50.0) * settings.SECTOR_RESEARCH_WEIGHT))
        b.grade = ("强" if b.score >= settings.SECTOR_STRONG_THRESHOLD
                   else "中" if b.score >= settings.SECTOR_MEDIUM_THRESHOLD
                   else "弱")
    return boards


def analyze(
    quotes: list[SectorQuote],
    research_scores: dict[str, tuple[float, str]] | None = None,
) -> list[SectorAnalysis]:
    """融合 → 评分（含研报维度）→ 分级，返回全部板块（含强/中/弱）。"""
    em_sources = [q for q in quotes if q.source == "eastmoney"]
    primary = "eastmoney" if em_sources else "sina"
    return score_boards(merge_boards(quotes, primary_source=primary), research_scores=research_scores)
