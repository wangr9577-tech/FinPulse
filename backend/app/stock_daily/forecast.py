"""东财业绩预告抓取（datacenter-web 结构化接口）。

同一股票同日可能有多条（净利润/扣非/营收），按股票去重，优先保留
PREDICT_CONTENT 含「归属于上市公司股东的净利润」那条，其次含「净利润」，否则第一条。
失败降级返回空列表（不抛出）。
"""
import logging
from datetime import date
from typing import Any

import httpx

from app.stock_daily.http_client import build_headers, request_with_retry
from app.stock_daily.models import ForecastRow

logger = logging.getLogger(__name__)

FORECAST_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
FORECAST_REFERER = "https://data.eastmoney.com/bbsj/yjyg.html"
FORECAST_REPORT_NAME = "RPT_PUBLIC_OP_NEWPREDICT"


def _to_float(v: Any) -> float | None:
    if v in ("", None, "-"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_row(row: dict) -> ForecastRow | None:
    code = str(row.get("SECURITY_CODE") or "").strip()
    if not code:
        return None
    return ForecastRow(
        stock_code=code,
        stock_name=str(row.get("SECURITY_NAME_ABBR") or ""),
        forecast_type=str(row.get("PREDICT_TYPE") or ""),
        change_lower=_to_float(row.get("ADD_AMP_LOWER")),
        change_upper=_to_float(row.get("ADD_AMP_UPPER")),
        content=str(row.get("PREDICT_CONTENT") or ""),
    )


def _pick_best(rows: list[ForecastRow]) -> ForecastRow:
    """同股票多条预告，优先「归属于上市公司股东的净利润」，其次「净利润」。"""
    for kw in ("归属于上市公司股东的净利润", "净利润"):
        for r in rows:
            if kw in r.content:
                return r
    return rows[0]


def fetch_forecasts(end_date: str | date) -> list[ForecastRow]:
    """抓取当日（NOTICE_DATE = end_date）业绩预告，按股票去重。失败降级空列表。"""
    end = end_date if isinstance(end_date, date) else date.fromisoformat(str(end_date))
    iso = end.isoformat()
    out: list[ForecastRow] = []
    try:
        with httpx.Client(timeout=20) as client:
            resp = request_with_retry(
                client, "GET", FORECAST_URL, max_retries=1,
                params={
                    "reportName": FORECAST_REPORT_NAME,
                    "columns": "ALL",
                    "filter": f"(NOTICE_DATE>='{iso}')(NOTICE_DATE<='{iso}')",
                    "pageNumber": 1, "pageSize": 500,
                    "sortColumns": "NOTICE_DATE", "sortTypes": "-1",
                },
                headers=build_headers(FORECAST_REFERER), timeout=20,
            )
            if resp.status_code != 200:
                logger.warning("业绩预告抓取失败: HTTP %s", resp.status_code)
                return out
            data = ((resp.json().get("result") or {}).get("data") or [])
        # 解析循环同样纳入保护：data 若非纯 dict 列表（错误响应里 data 为 dict
        # 或含非 dict 元素），_parse_row 的 row.get(...) 会抛 AttributeError，
        # 必须在此降级为空列表，兑现「失败不抛出」。
        groups: dict[str, list[ForecastRow]] = {}
        for row in data:
            r = _parse_row(row)
            if r:
                groups.setdefault(r.stock_code, []).append(r)
        return [_pick_best(v) for v in groups.values()]
    except Exception as exc:
        logger.warning("业绩预告抓取失败: %r", exc)
        return out
