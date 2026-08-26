"""板块工作流编排：抓取 → 融合评分 → 领涨股 → 强/中点评（并发）。"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import httpx

from app.stock_daily.config import settings
from app.stock_daily.models import SectorAnalysis, SectorQuote
from app.stock_daily.research.crawler import fetch_industry_reports
from app.stock_daily.sector import analyzer as sector_analyzer
from app.stock_daily.sector import crawler as sector_crawler
from app.stock_daily.sector import research_view
from app.stock_daily.sector import scorer as sector_scorer


def _comment_guard(board: SectorAnalysis) -> None:
    """单板块点评：异常降级为 "—"，不阻断其余板块。"""
    try:
        board.comment = sector_analyzer.comment_sector(board)
    except Exception:
        board.comment = "—"


def analyze_sectors(ann_date: date, logger: logging.Logger) -> list[SectorAnalysis]:
    """抓取三源板块 → 融合评分分级 → 强/中板块 DeepSeek 点评。

    返回强+中板块（已含评分/领涨股/点评）；弱板块不返回（不展示不点评）。
    单源/点评失败均降级，不阻断整体。ann_date 目前仅作签名占位（板块行情为实时数据）。
    """
    quotes: list[SectorQuote] = []
    try:
        with httpx.Client(timeout=20) as client:
            for fetcher in sector_crawler.FETCHERS:
                quotes += fetcher(client)
    except Exception as exc:
        logger.warning("板块抓取整体失败: %r", exc)
    if not quotes:
        logger.warning("板块数据为空（可能非交易时段或接口被限流），跳过板块分析")
        return []
    # 行业研报观点 → 板块研报分（失败降级为空，不阻断）
    research_scores: dict[str, tuple[float, str]] = {}
    try:
        ind_reports = fetch_industry_reports(ann_date)
        research_scores = research_view.build_industry_scores(ind_reports)
        logger.info(f"行业研报 {len(ind_reports)} 篇，命中板块 {len(research_scores)} 个")
    except Exception as exc:
        logger.warning(f"行业研报观点聚合失败，板块研报分降级为空: {exc!r}")
    try:
        boards = sector_scorer.analyze(quotes, research_scores=research_scores)
    except Exception as exc:
        logger.warning("板块评分失败: %r", exc)
        return []
    strong = [b for b in boards if b.grade == "强"]
    medium = [b for b in boards if b.grade == "中"]
    logger.info(f"板块分析：融合 {len(boards)} 个板块，强 {len(strong)} 个，中 {len(medium)} 个")
    candidates = strong + medium
    with ThreadPoolExecutor(max_workers=settings.SECTOR_COMMENT_CONCURRENCY) as ex:
        futures = {ex.submit(_comment_guard, b): b for b in candidates}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception:
                pass  # _comment_guard 已降级，此处仅兜底
    return candidates
