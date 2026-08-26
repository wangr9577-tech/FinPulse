"""四维交叉打分 + 候选池构造。

维度：公告利好程度(40%) / 研报评级(30%) / 目标价空间(20%) / 新鲜度(10%)。
候选池 = 重点研报覆盖的股票集合；当日有公告利好 → 交集，否则 → 研报单边。
目标价缺失记该维度中值 50，恒参与加权。
"""
from datetime import date

from app.stock_daily.config import settings
from app.stock_daily.models import (Announcement, AnalysisResult, ReportInsight,
                        ReportRow, StockCandidate)


def ann_score(level: str) -> float:
    return {"高": 100.0, "中": 75.0, "低": 50.0}.get(level, 0.0)


_RATING_RANK = {"买入": 3, "增持": 2, "中性": 1, "减持": 0, "卖出": -1}


def rating_score(rating: str, last_rating: str = "") -> float:
    """评级分：买入 100 / 增持 70 / 中性 40；较上次评级上调 +15。

    上调判定用评级名次比较（买入>增持>中性>减持>卖出），不再依赖 ratingChange
    字段——实测 ratingChange 3=维持/2=首次/1=下调，并非「>0 即上调」。
    """
    base = {"买入": 100.0, "增持": 70.0, "中性": 40.0}.get(rating, 0.0)
    cur = _RATING_RANK.get(rating)
    last = _RATING_RANK.get(last_rating)
    if cur is not None and last is not None and cur > last:
        base += 15.0
    return base


def freshness_score(publish_date: str, report_date: str) -> float:
    try:
        pub = date.fromisoformat(publish_date[:10])
        ref = date.fromisoformat(report_date[:10])
    except ValueError:
        return 0.0
    days = (ref - pub).days
    if days <= 0:
        return 100.0
    if days == 1:
        return 75.0
    if 2 <= days <= 3:
        return 50.0
    return 0.0


def upside_score(upside: float) -> float:
    """目标价空间 → 0-100。真实负空间(现价高于目标价)记 0；缺失(0)记中值 50；
    上限 PICK_UPSIDE_TOP 封顶 100。"""
    if upside < 0:
        return 0.0
    if upside == 0:
        return 50.0
    top = settings.PICK_UPSIDE_TOP * 100.0
    return min(upside / top * 100.0, 100.0)


def _weighted(ann: float, rating: float, upside: float, fresh: float) -> float:
    """四维加权求分（权重来自配置）。"""
    return (ann * settings.PICK_ANN_WEIGHT
            + rating * settings.PICK_RATING_WEIGHT
            + upside * settings.PICK_PRICE_WEIGHT
            + fresh * settings.PICK_FRESH_WEIGHT)


def build_candidate(
    stock_code: str, stock_name: str,
    ann_level: str, rating: str, last_rating: str,
    price: float, aim_l: float, aim_t: float,
    publish_date: str, report_date: str,
) -> StockCandidate:
    """单股候选打分（目标价缺失时 upside=0 → 记中值 50）。"""
    from src.research.quote import upside_pct
    upside = upside_pct(price, aim_l, aim_t)
    score = _weighted(ann_score(ann_level), rating_score(rating, last_rating),
                      upside_score(upside), freshness_score(publish_date, report_date))
    return StockCandidate(
        stock_code=stock_code, stock_name=stock_name,
        score=round(score, 2), ann_level=ann_level, rating=rating,
        target_upside=round(upside, 2),
        source_type="交集" if ann_level else "研报单边",
    )


def _report_key(publish_date: str) -> date:
    """研报日期排序键：取日期部分转 date（容忍 "2026-08-12 00:00:00.000"）。"""
    try:
        return date.fromisoformat(publish_date[:10])
    except (ValueError, TypeError):
        return date.min


def normalize_rows(
    rows: list[tuple[Announcement, AnalysisResult] | ReportRow],
) -> list[tuple[Announcement, AnalysisResult]]:
    """rows 兼容两种形态：ReportRow（.announcement/.analysis）或 (Announcement, AnalysisResult) 元组。

    pipeline 传 ReportRow 对象行；runner/测试可能传元组。统一转成元组列表。
    """
    out: list[tuple[Announcement, AnalysisResult]] = []
    for item in rows:
        if hasattr(item, "announcement") and hasattr(item, "analysis"):
            out.append((item.announcement, item.analysis))
        else:
            out.append((item[0], item[1]))
    return out


def build_candidates(
    rows: list[tuple[Announcement, AnalysisResult] | ReportRow],
    insights: list[ReportInsight],
    prices: dict[str, float],
    report_date: str,
) -> list[StockCandidate]:
    """候选池 = 重点研报覆盖的股票；有公告利好 → 交集。

    insights 中同股票多篇研报取最新（publish_date 最大）那篇打分。
    """
    rows = normalize_rows(rows)
    ann_map: dict[str, str] = {}
    for a, r in rows:
        if r.sentiment == "利好" and a.stock_code not in ann_map:
            ann_map[a.stock_code] = r.level

    best: dict[str, ReportInsight] = {}
    for ins in insights:
        code = ins.report.stock_code
        if code not in best or _report_key(ins.report.publish_date) > _report_key(best[code].report.publish_date):
            best[code] = ins

    out: list[StockCandidate] = []
    for code, ins in best.items():
        rp = ins.report
        price = prices.get(code, 0.0)
        out.append(build_candidate(
            stock_code=code, stock_name=rp.stock_name,
            ann_level=ann_map.get(code, ""),
            rating=rp.rating, last_rating=rp.last_rating,
            price=price, aim_l=rp.aim_price_l, aim_t=rp.aim_price_t,
            publish_date=rp.publish_date, report_date=report_date,
        ))
    out.sort(key=lambda c: c.score, reverse=True)
    return out
