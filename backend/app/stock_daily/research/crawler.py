"""东财 reportapi 研报元数据抓取（qType=0 个股 + qType=1 行业）。

实测（2026-08-12）：reportapi.eastmoney.com 免鉴权返回 JSON，字段见 _parse_report_row / _parse_industry_row。
限流红线：东财按 IP 限流，串行请求 ≥1s 间隔 + 随机抖动（RESEARCH_QA_INTERVAL）。
观点扩展源预留：EXTRA_VIEW_FETCHERS 为空列表，未来接入评论/快讯源时插入 fetcher。
"""
import logging
import random
import threading
import time
from datetime import date, timedelta
from typing import Any, Callable

import httpx

from app.stock_daily.http_client import build_headers, request_with_retry
from app.stock_daily.models import IndustryReport, ResearchReport

logger = logging.getLogger(__name__)

REPORTAPI_BASE = "https://reportapi.eastmoney.com/report/list"
REPORTAPI_REFERER = "https://data.eastmoney.com/report/zw_stock.jshtml"
PDF_BASE = "https://pdf.dfcfw.com/pdf"
PAGE_SIZE = 50
MAX_PAGES = 20

# 观点扩展源预留位：未来接财联社电报等评论/快讯源时追加 fetcher
EXTRA_VIEW_FETCHERS: list[Callable[[httpx.Client], list[ResearchReport]]] = []

# 串行限流状态：读-判断-sleep-写须原子，防止并发调用方同时越过间隔放行
_last_request_ts = 0.0
_lock = threading.Lock()


def _throttle() -> None:
    """串行限流：距上次请求不足 RESEARCH_QA_INTERVAL 则 sleep 补足。"""
    global _last_request_ts
    from app.stock_daily.config import settings
    interval = settings.RESEARCH_QA_INTERVAL
    with _lock:
        now = time.time()
        elapsed = now - _last_request_ts
        if elapsed < interval:
            time.sleep(interval - elapsed + random.uniform(0.0, 0.2))
        _last_request_ts = time.time()


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v not in ("", None) else default
    except (TypeError, ValueError):
        return default


def _parse_report_row(row: dict) -> ResearchReport | None:
    """单行 → ResearchReport；缺 stockCode 无法定位标的 → None。"""
    code = str(row.get("stockCode") or "").strip()
    if not code:
        return None
    info_code = str(row.get("infoCode") or "")
    pdf_url = f"{PDF_BASE}/H3_{info_code}_1.pdf" if info_code else ""
    return ResearchReport(
        stock_code=code,
        stock_name=str(row.get("stockName") or ""),
        title=str(row.get("title") or ""),
        org_name=str(row.get("orgName") or ""),
        researcher=str(row.get("researcher") or ""),
        publish_date=str(row.get("publishDate") or ""),
        rating=str(row.get("emRatingName") or ""),
        last_rating=str(row.get("lastEmRatingName") or ""),
        rating_change=int(_to_float(row.get("ratingChange"))),
        aim_price_t=_to_float(row.get("indvAimPriceT")),
        aim_price_l=_to_float(row.get("indvAimPriceL")),
        eps_forecast=_to_float(row.get("predictThisYearEps")),
        pdf_url=pdf_url,
        source="eastmoney",
    )


def _parse_industry_row(row: dict) -> IndustryReport | None:
    """qType=1 单行 → IndustryReport；缺 industryName 无法定位板块 → None。"""
    ind_name = str(row.get("industryName") or "").strip()
    if not ind_name:
        return None
    info_code = str(row.get("infoCode") or "")
    pdf_url = f"{PDF_BASE}/H3_{info_code}_1.pdf" if info_code else ""
    return IndustryReport(
        industry_name=ind_name,
        title=str(row.get("title") or ""),
        org_name=str(row.get("orgName") or ""),
        researcher=str(row.get("researcher") or ""),
        publish_date=str(row.get("publishDate") or ""),
        rating=str(row.get("sRatingName") or ""),
        em_rating=str(row.get("emRatingName") or ""),
        pdf_url=pdf_url,
        source="eastmoney",
    )


def _fetch_reports(
    qtype: int,
    parse_row: Callable[[dict], Any],
    end_date: str | date,
    lookback_days: int | None = None,
) -> list:
    """抓取 [end_date - lookback, end_date] 的研报元数据（通用分页，qtype 区分个股/行业）。

    失败降级返回空列表（不抛出）。lookback_days=None 用 settings.REPORT_LOOKBACK_DAYS。
    分页终止：空 data 页或已收齐 hits 总数即停（避免死循环）。
    """
    from app.stock_daily.config import settings
    lookback = lookback_days if lookback_days is not None else settings.REPORT_LOOKBACK_DAYS
    end = end_date if isinstance(end_date, date) else date.fromisoformat(str(end_date))
    begin = end - timedelta(days=lookback)
    out: list = []
    page = 1
    received = 0
    try:
        with httpx.Client(timeout=20) as client:
            while page <= MAX_PAGES:
                _throttle()
                resp = request_with_retry(
                    client, "GET", REPORTAPI_BASE,
                    max_retries=1,
                    params={
                        "qType": qtype, "pageSize": PAGE_SIZE, "pageNo": page,
                        "beginTime": begin.isoformat(), "endTime": end.isoformat(),
                    },
                    headers=build_headers(REPORTAPI_REFERER), timeout=20,
                )
                if resp.status_code != 200:
                    logger.warning("东财研报抓取失败: HTTP %s", resp.status_code)
                    return out
                try:
                    payload = resp.json()
                    data = payload.get("data") or []
                    hits = int(payload.get("hits") or 0)
                except Exception as exc:
                    logger.warning("东财研报 JSON 解析失败: %r", exc)
                    return out
                if not isinstance(data, list):
                    data = []
                for row in data:
                    r = parse_row(row)
                    if r:
                        out.append(r)
                        received += 1
                if not data or (hits and received >= hits) or page >= MAX_PAGES:
                    break
                page += 1
    except Exception as exc:
        logger.warning("东财研报抓取失败: %r", exc)
        return out
    return out


def fetch_reports(
    end_date: str | date,
    lookback_days: int | None = None,
) -> list[ResearchReport]:
    """抓取个股研报（qType=0）。"""
    return _fetch_reports(0, _parse_report_row, end_date, lookback_days)


def fetch_industry_reports(
    end_date: str | date,
    lookback_days: int | None = None,
) -> list[IndustryReport]:
    """抓取行业研报（qType=1）。"""
    return _fetch_reports(1, _parse_industry_row, end_date, lookback_days)
