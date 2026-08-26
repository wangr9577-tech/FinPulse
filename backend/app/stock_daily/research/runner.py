"""研报工作流编排：抓研报 → 提取观点 → 查价 → 打分 → 选股。"""
import logging
from datetime import date

from app.stock_daily.models import (Announcement, AnalysisResult, ReportInsight,
                        ReportRow, ResearchReport, StockCandidate, StockPicks)
from app.stock_daily.research.crawler import fetch_reports
from app.stock_daily.research.picker import build_picks
from app.stock_daily.research.quote import fetch_prices
from app.stock_daily.research.reader import extract_insights
from app.stock_daily.research.scorer import _report_key, build_candidates, normalize_rows


def _latest_insight(insights) -> dict[str, ReportInsight]:
    """同股多篇研报取最新（publish_date 最大），与 scorer.build_candidates 规则一致。

    返回 {code: insight}，供 research_brief 与打分对齐，避免取到旧的/覆盖态观点。
    """
    best: dict[str, ReportInsight] = {}
    for ins in insights:
        code = ins.report.stock_code
        if code not in best or _report_key(ins.report.publish_date) > _report_key(best[code].report.publish_date):
            best[code] = ins
    return best


def analyze_stocks(
    rows: list[tuple[Announcement, AnalysisResult] | ReportRow],
    ann_date: str | date,
    logger: logging.Logger,
) -> StockPicks:
    """每日选股推荐。任何环节失败降级，不抛出。

    rows: pipeline 已判定的利好公告行（ReportRow 或 (Announcement, AnalysisResult) 元组均可）。
    ann_date: 报告日期。返回 StockPicks（可能带 note/degraded）。
    """
    rows = normalize_rows(rows)
    ad = ann_date if isinstance(ann_date, date) else date.fromisoformat(str(ann_date))
    if not rows:
        return StockPicks(date=ad, note="今日无利好公告，跳过选股")
    logger.info("开始券商研报分析与选股推荐...")
    try:
        reports = fetch_reports(ad)
    except Exception as exc:
        logger.warning("研报抓取失败: %r", exc)
        return StockPicks(date=ad, note="研报数据获取失败", degraded=True)
    if not reports:
        logger.warning("研报数据为空，选股推荐降级")
        return StockPicks(date=ad, note="今日无重点研报", degraded=True)
    logger.info(f"研报元数据 {len(reports)} 条")

    # 重点研报：仅保留买入/增持评级（排除中性及以下）
    key_reports = [r for r in reports if r.rating in ("买入", "增持")]
    if not key_reports:
        return StockPicks(date=ad, note="今日无买入/增持研报", degraded=True)
    logger.info(f"重点研报（买入/增持）{len(key_reports)} 篇")

    insights = extract_insights(key_reports, ad, logger)
    prices = fetch_prices([r.stock_code for r in key_reports])
    cands = build_candidates(rows, insights, prices, ad.isoformat())
    if not cands:
        return StockPicks(date=ad, note="今日无符合条件个股", degraded=True)

    # brief 对齐打分去重规则：ann 取首个（scorer ann_map 首次出现，级别最高）；
    # research 取最新 publish_date（scorer 打分取最新那篇）。
    ann_brief: dict[str, str] = {}
    ann_links: dict[str, list[str]] = {}
    for a, _ in rows:
        if a.stock_code not in ann_brief:
            ann_brief[a.stock_code] = _brief_ann(a)
        links = ann_links.setdefault(a.stock_code, [])
        if a.pdf_url and a.pdf_url not in links:
            links.append(a.pdf_url)
    latest = _latest_insight(insights)
    research_brief = {code: _brief_research(ins) for code, ins in latest.items()}
    # 该股当日全部买入/增持研报完整观点（供选股详情逐篇展示，按时间新→旧）
    reports_by_code: dict[str, list[ReportInsight]] = {}
    for ins in insights:
        reports_by_code.setdefault(ins.report.stock_code, []).append(ins)
    for code in reports_by_code:
        reports_by_code[code].sort(key=lambda i: _report_key(i.report.publish_date), reverse=True)
    picks = build_picks(cands, ad, ann_brief, research_brief, ann_links, reports_by_code)
    logger.info(f"选股推荐 {len(picks.picks)} 支")
    return picks


def _brief_ann(a: Announcement) -> str:
    return a.title


def _brief_research(i) -> str:
    return i.summary or i.report.title
