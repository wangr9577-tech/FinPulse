"""全流程编排：爬取 → 分析 → 报告 → 发送 → 清理，并维护 state.json 幂等。"""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

import httpx

from app.stock_daily.config import settings
from app.stock_daily import logger as logger_mod
from app.stock_daily.analyzer import analyze_one, judge_by_title
from app.stock_daily.crawlers import merge, sse as sse_crawler, szse as szse_crawler
from app.stock_daily.daily_report import build_daily_report
from app.stock_daily.forecast import fetch_forecasts
from app.stock_daily.models import AnalysisResult, Announcement, ReportData, ReportRow, StockPicks
from app.stock_daily.pdf_parser import download_pdf, parse_with_pypdf
from app.stock_daily.planner import plan_by_title
from app.stock_daily.research.runner import analyze_stocks
from app.stock_daily.sector.runner import analyze_sectors
from app.stock_daily.stock_names import fetch_stock_names
from app.stock_daily.trading_calendar import is_trading_day

_LEVEL_ORDER = {"高": 0, "中": 1, "低": 2}


def ann_key(a: Announcement) -> str:
    return f"{a.stock_code}|{a.title}"


def _safe_key(key: str) -> str:
    """将 key 转换为 Windows 文件系统安全的名字（非法字符与控制字符替换、先截断后去空白）。"""
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", key)
    return safe[:80].strip(" .") or "_"


# ---------- 状态 ----------

def _load_state() -> dict:
    if settings.STATE_FILE.exists():
        try:
            data = json.loads(settings.STATE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    try:
        settings.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        settings.STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        # 邮件已送达，状态写入失败不改变成功语义，仅告警（防止下轮重复发送需人工关注）
        logger_mod.setup_logger("pipeline", settings.LOGS_DIR).warning(
            f"状态写入失败（邮件已发送，注意防重）：{exc!r}"
        )


# ---------- 分析缓存（断点续跑） ----------

def _analysis_cache_path(ann_date: date) -> Path:
    return settings.ANALYSIS_DIR / f"{ann_date.isoformat()}.json"


def _load_analysis_cache(ann_date: date) -> dict:
    p = _analysis_cache_path(ann_date)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_analysis_cache(ann_date: date, cache: dict) -> None:
    p = _analysis_cache_path(ann_date)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 主流程 ----------

def _enrich_stock_names(announcements: list[Announcement], logger: logging.Logger) -> None:
    """补齐缺失股票名称（上交所接口不返回简称，用东财按代码批量查询补齐）。

    全失败仅告警，名称保留为空（报告显示为 '-'），不阻断流程。
    """
    missing = [a for a in announcements if not a.stock_name]
    if not missing:
        return
    try:
        with httpx.Client(timeout=20) as client:
            name_map = fetch_stock_names(client, (a.stock_code for a in missing))
        filled = 0
        for a in missing:
            n = name_map.get(a.stock_code)
            if n:
                a.stock_name = n
                filled += 1
        logger.info(f"补齐缺失股票名 {filled}/{len(missing)}")
    except Exception as exc:
        logger.warning(f"股票名补齐失败，缺失名称显示为 '-'：{exc!r}")


def _review_one(a: Announcement, pdf: Path | None) -> AnalysisResult:
    """单条复核：pypdf 解析正文 → DeepSeek 全文判定。解析为空走标题降级。

    analyze_one 内部自带 try/except 降级，正常不会抛异常。
    """
    a.full_text = parse_with_pypdf(pdf, settings.PDF_TEXT_CHARS) if pdf else ""
    return analyze_one(a)


def _review_pending(
    ann_date: date, pending: list[Announcement], logger: logging.Logger
) -> dict[str, AnalysisResult]:
    """中性待复核：并发下载 PDF → 并发 pypdf 解析 + DeepSeek 全文判定。

    仅用 pypdf 快通道（0.1s 级），无 MinerU 兜底：扫描件/复杂版式提取过短时
    文本留空，公告降级为标题判定（analyze_one 对空正文自行处理）。

    解析+判定阶段与标题判定保持相同并发度（ANALYZE_CONCURRENCY），
    单条异常不阻断整批。返回 key→AnalysisResult（覆盖全部 pending，
    含无 PDF 的公告——以标题降级判定）。
    """
    results: dict[str, AnalysisResult] = {}
    pdf_dir = settings.PDFS_DIR / ann_date.isoformat()

    pdf_map: dict[str, Path] = {}
    with httpx.Client(timeout=60) as client, ThreadPoolExecutor(
        max_workers=settings.DOWNLOAD_CONCURRENCY
    ) as ex:
        futures = {
            ex.submit(download_pdf, a.pdf_url, pdf_dir / _safe_key(ann_key(a)), client): ann_key(a)
            for a in pending if a.pdf_url
        }
        for fut in as_completed(futures):
            k = futures[fut]
            try:
                p = fut.result()
                if p:
                    pdf_map[k] = p
            except Exception:
                continue

    with ThreadPoolExecutor(max_workers=settings.ANALYZE_CONCURRENCY) as ex:
        futures = {
            ex.submit(_review_one, a, pdf_map.get(ann_key(a))): ann_key(a)
            for a in pending
        }
        for fut in as_completed(futures):
            k = futures[fut]
            try:
                results[k] = fut.result()
            except Exception:
                results[k] = AnalysisResult(sentiment="中性", level="低",
                                            reason="复核异常（降级）", degraded=True)
    return results


def _latest_analyzed_pending_date(state: dict) -> date | None:
    """找最近一个「已分析但未发送」的日期（send 模式不传日期时的兜底）。"""
    candidates = []
    for iso, entry in state.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("analyzed") and not entry.get("sent"):
            try:
                candidates.append(date.fromisoformat(iso))
            except ValueError:
                continue
    return max(candidates) if candidates else None


def run_pipeline(
    ann_date: date | None = None, *,
    force: bool = False, dry_run: bool = False,
    phase: str = "full",
) -> dict:
    """执行全流程（平台接入版）：爬取 → 分析 → 板块 → 选股 → 业绩预告 → 组装 DailyReportData。

    phase 保留仅为兼容外部签名（full/analyze/send），本平台不使用 Word/邮件，
    无 send 分支——一切以「返回 DailyReportData 的 JSON 字典」为准。
    返回组装好的 `DailyReportData.model_dump(mode="json")`；无数据时返回空 dict。
    """
    logger = logger_mod.setup_logger("pipeline", settings.LOGS_DIR)

    ann_date = ann_date or date.today()
    # 平台接入：不做"已发送"幂等（无邮件），以 Mongo upsert 作为每日幂等；交易日门控保留
    if not dry_run and not is_trading_day(ann_date):
        logger.info(f"{ann_date} 非交易日，退出")
        return {}

    # 并行爬取两所（每所内部也并行拉页）
    logger.info(f"开始并行爬取 {ann_date} 公告...")

    fetch_failures: list[str] = []

    def _fetch_exchange(fetch_fn, label: str) -> list[Announcement]:
        try:
            with httpx.Client(timeout=20) as client:
                return fetch_fn(ann_date, client)
        except Exception as e:
            logger.error(f"{label} 爬取失败: {e!r}")
            fetch_failures.append(label)
            return []

    with ThreadPoolExecutor(max_workers=2) as ex:
        future_sse = ex.submit(_fetch_exchange, sse_crawler.fetch_announcements, "上交所")
        future_szse = ex.submit(_fetch_exchange, szse_crawler.fetch_announcements, "深交所")
        sse_items = future_sse.result()
        szse_items = future_szse.result()
    logger.info(f"上交所 {len(sse_items)} 条, 深交所 {len(szse_items)} 条")
    announcements = merge.merge_announcements(sse_items, szse_items)
    if not announcements:
        logger.warning("当日无公告数据，不发空报告")
        return True
    logger.info(f"合并后共 {len(announcements)} 条")
    sources_note = f"以下数据源本次获取失败，报告可能不完整：{'、'.join(fetch_failures)}" if fetch_failures else ""
    _enrich_stock_names(announcements, logger)

    # 标题情绪判定 + 分桶（利好优先）
    logger.info("开始标题情绪判定（利好优先）...")
    cache = _load_analysis_cache(ann_date)
    fresh: list[Announcement] = []
    cached: list[tuple[Announcement, AnalysisResult]] = []
    for a in announcements:
        k = ann_key(a)
        if k not in cache:
            fresh.append(a)
            continue
        try:
            cached.append((a, AnalysisResult(**cache[k])))
        except Exception:
            # 单条缓存损坏（手改坏/字段漂移）不阻断整体：按 fresh 重判
            fresh.append(a)

    judged: dict[str, AnalysisResult] = {}
    if fresh:
        with ThreadPoolExecutor(max_workers=settings.ANALYZE_CONCURRENCY) as ex:
            futures = {ex.submit(judge_by_title, a): ann_key(a) for a in fresh}
            for fut in as_completed(futures):
                k = futures[fut]
                try:
                    judged[k] = fut.result()
                except Exception:
                    judged[k] = AnalysisResult(sentiment="中性", level="低",
                                               reason="标题判定异常（降级）", degraded=True)

    plan = plan_by_title(fresh, lambda a: judged[ann_key(a)])
    pending_keys = {ann_key(a) for a in plan.pending}
    # 直接定论部分（利好/利空/中性例行）写入缓存；pending 复核后写入最终结果
    for k, j in judged.items():
        if k not in pending_keys:
            cache[k] = j.model_dump(mode="json")
    _save_analysis_cache(ann_date, cache)
    logger.info(f"标题判定：利好直出 {len(plan.positive)} 条，待复核 {len(plan.pending)} 条，舍弃 {plan.discarded} 条")

    # 待下载复核：仅保留判定为利好的
    review_positive: list[tuple[Announcement, AnalysisResult]] = []
    if plan.pending:
        logger.info(f"{len(plan.pending)} 条中性公告进入下载复核...")
        results = _review_pending(ann_date, plan.pending, logger)
        for k, r in results.items():
            cache[k] = r.model_dump(mode="json")
        _save_analysis_cache(ann_date, cache)
        for a in plan.pending:
            r = results.get(ann_key(a))
            if r and r.sentiment == "利好":
                review_positive.append((a, r))
        logger.info(f"复核后利好 {len(review_positive)} 条")

    # 组装报告行（仅利好；缓存命中的历史结果也按利好过滤）
    rows = [ReportRow(announcement=a, analysis=r) for a, r in plan.positive + review_positive]
    rows += [ReportRow(announcement=a, analysis=r) for a, r in cached if r.sentiment == "利好"]
    rows.sort(key=lambda r: _LEVEL_ORDER.get(r.analysis.level, 9))
    counts = {"利好": len(rows), "利空": 0, "中性": 0}
    level_counts: dict[str, int] = {"高": 0, "中": 0, "低": 0}
    for r in rows:
        level_counts[r.analysis.level] = level_counts.get(r.analysis.level, 0) + 1
    data = ReportData(
        date=ann_date, total=len(rows), sentiment_counts=counts,
        high_level=[r for r in rows if r.analysis.level == "高"],
        medium_level=[r for r in rows if r.analysis.level == "中"],
        low_level=[r for r in rows if r.analysis.level == "低"],
        full_list=rows,
        degraded_rows=[],
        tiered_mode=False, tiered_reason="", sources_note=sources_note,
        level_counts=level_counts,
    )

    # 板块分析 + 研报选股 + 整合 + 生成 Word 与邮件摘要
    sector_boards = analyze_sectors(ann_date, logger)
    # 研报选股异常不阻断日报：降级为无选股推荐继续出报告
    try:
        stock_picks = analyze_stocks(rows, ann_date, logger)
    except Exception as exc:
        logger.warning(f"研报选股异常，报告不含选股推荐：{exc!r}")
        stock_picks = StockPicks(date=ann_date, note="研报选股异常", degraded=True)
    # 业绩预告抓取内部已降级（失败返回空列表，不抛出），无需再包 try/except
    forecasts = fetch_forecasts(ann_date)
    logger.info(f"业绩预告 {len(forecasts)} 条")
    daily = build_daily_report(data, sector_boards, ann_date, stock_picks=stock_picks, forecasts=forecasts)
    logger.info(
        f"投资日报组装完成: {ann_date} | 公告 {len(rows)} 条, "
        f"强势板块 {len(daily.sectors_strong)} 个, "
        f"选股 {len(daily.stock_picks.picks) if daily.stock_picks else 0} 支, "
        f"业绩预告 {len(daily.forecasts)} 条"
    )

    # 平台接入：无需 Word/邮件，直接把 DailyReportData 转成可存 Mongo 的 JSON 字典
    return daily.model_dump(mode="json")


