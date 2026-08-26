"""行业研报观点 → 板块研报分。

把 reportapi qType=1 行业研报（industryName 标签 + 券商行业评级）聚合到东财板块
（按归一化名对齐），输出每个板块的研报维度得分（0-100，缺研报 50）与观点摘要。
"""
from collections import defaultdict

from app.stock_daily.models import IndustryReport
from app.stock_daily.sector.scorer import normalize_board_name

# 券商行业评级 → 看多/看空词表（其余：中性/持有/标配/观望/未知 记中性 0）
_BULLISH = {"看好", "推荐", "买入", "增持", "强于大市", "超配", "优于大市", "领先大市"}
_BEARISH = {"看淡", "回避", "卖出", "减持", "弱于大市", "低配", "跑输大市", "落后大市"}


def industry_sentiment(rating: str) -> float:
    """券商行业评级 → 情绪分：看多 +1 / 看空 -1 / 其余 0。"""
    r = (rating or "").strip()
    if r in _BULLISH:
        return 1.0
    if r in _BEARISH:
        return -1.0
    return 0.0


def _dedup_reports(reports: list[IndustryReport]) -> list[IndustryReport]:
    """同一（行业, 券商）仅保留 publish_date 最新一篇。

    周报/月报等例行报告按券商每周发布，窗口内可能叠加事件点评/深度报告；
    若不去重，同一券商对同一行业的重复覆盖会按篇数重复计数，稀释观点信噪比。
    缺券商名的研报不参与去重（避免误合并为单篇）。
    """
    latest: dict[tuple[str, str], IndustryReport] = {}
    no_org: list[IndustryReport] = []
    for r in reports:
        key = normalize_board_name(r.industry_name)
        org = (r.org_name or "").strip()
        if not org:
            no_org.append(r)
            continue
        k = (key, org)
        if k not in latest or r.publish_date > latest[k].publish_date:
            latest[k] = r
    return list(latest.values()) + no_org


def build_industry_scores(
    reports: list[IndustryReport],
) -> dict[str, tuple[float, str]]:
    """按行业聚合同名研报 → {归一化行业名: (研报分 0-100, 观点摘要)}。

    研报分 = 50 + 50 * 平均情绪分（全看多 100 / 全看空 0 / 全中性 50）。
    评级优先 sRatingName（行业评级），其次 emRatingName（个股评级词表 fallback）。
    先按（行业, 券商）去重保留最新一篇，避免例行周报重复计数。
    """
    reports = _dedup_reports(reports)
    groups: dict[str, list[float]] = defaultdict(list)
    for r in reports:
        key = normalize_board_name(r.industry_name)
        if not key:
            continue
        rating = r.rating or r.em_rating
        groups[key].append(industry_sentiment(rating))
    out: dict[str, tuple[float, str]] = {}
    for key, sents in groups.items():
        avg = sum(sents) / len(sents)
        score = 50.0 + 50.0 * avg
        n = len(sents)
        pos = sum(1 for s in sents if s > 0)
        neg = sum(1 for s in sents if s < 0)
        if pos and not neg:
            note = f"{n}篇看好"
        elif neg and not pos:
            note = f"{n}篇看空"
        elif pos and neg:
            note = f"{n}篇研报（{pos}看多 {neg}看空）"
        else:
            note = f"{n}篇中性"
        out[key] = (round(score, 2), note)
    return out
