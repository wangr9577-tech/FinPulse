"""上交所公告爬取：GET queryLatestBulletinNew.do（JSONP 响应）。

关键反爬：Referer 必须带 www.sse.com.cn 披露页，否则 403/断连。
"""
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import httpx

from app.stock_daily.config import settings
from app.stock_daily.http_client import build_headers, request_with_retry
from app.stock_daily.models import Announcement

logger = logging.getLogger(__name__)

SSE_URL = "http://query.sse.com.cn/infodisplay/queryLatestBulletinNew.do"
SSE_REFERER = "http://www.sse.com.cn/disclosure/listedinfo/announcement/"
SSE_PDF_PREFIX = "http://static.sse.com.cn"
PAGE_SIZE = 25


def _strip_jsonp(text: str) -> dict:
    """剥掉 JSONP 回调外壳，返回内层 JSON 对象。"""
    start = text.find("(")
    end = text.rfind(")")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("非 JSONP 响应")
    return json.loads(text[start + 1:end])


def _params(ann_date: date, page_no: int) -> dict:
    return {
        "jsonCallBack": "jsonpCallback123",
        "isPagination": "true",
        "productId": "",
        "keyWord": "",
        "reportType2": "",
        "reportType": "",
        "beginDate": ann_date.isoformat(),
        "endDate": ann_date.isoformat(),
        "pageHelp.pageSize": PAGE_SIZE,
        "pageHelp.pageCount": 50,
        "pageHelp.pageNo": page_no,
        # 实测（2026-08）：服务端用 beginPage/endPage 选择返回哪一页，pageNo 恒返回首屏。
        # 因此 beginPage=endPage=pageNo 才能拉到对应页；固定 1/5 会导致所有页重复、漏抓绝大部分公告。
        "pageHelp.beginPage": page_no,
        "pageHelp.cacheSize": 1,
        "pageHelp.endPage": page_no,
        "_": int(time.time() * 1000),
    }


def _first(row: dict, keys: list[str]) -> str:
    for k in keys:
        v = row.get(k)
        if v:
            return str(v)
    return ""


def _parse_row(row: dict, ann_date: date) -> Announcement:
    url = _first(row, ["URL"])
    return Announcement(
        stock_code=_first(row, ["security_Code"]),
        stock_name=_first(row, ["SECURITY_NAME", "security_Abbr", "SECURITY_NAME_ABBR"]),
        title=_first(row, ["title"]),
        category=_first(row, ["bulletin_Type"]),
        pdf_url=(SSE_PDF_PREFIX + url) if url else "",
        exchange="SSE",
        announce_date=ann_date,
    )


def _fetch_page(
    client: httpx.Client, ann_date: date, page_no: int, headers: dict
) -> tuple[int, list[Announcement]]:
    """抓取单页，返回 (pageCount, 本页公告)。"""
    resp = request_with_retry(
        client, "GET", SSE_URL, params=_params(ann_date, page_no),
        headers=headers, timeout=20,
    )
    if resp.status_code != 200:
        return 0, []
    data = _strip_jsonp(resp.text)
    page_help = data.get("pageHelp") or {}
    rows = page_help.get("data") or []
    try:
        page_count = int(page_help.get("pageCount") or 0)
        total = int(page_help.get("total") or 0)
    except (TypeError, ValueError):
        page_count = 0
        total = 0
    anns = [_parse_row(row, ann_date) for row in rows]
    return page_count, total, [a for a in anns if a.title]


def fetch_announcements(ann_date: date, client: httpx.Client) -> list[Announcement]:
    """抓取上交所当日全部公告：首页定页数，其余页并行拉取。

    实测（2026-08）：服务端用 beginPage/endPage 选页（见 _params），
    各页拉取后与首页 total 比对，若远少于总数则告警，避免静默漏抓。
    """
    headers = build_headers(SSE_REFERER)
    headers["Host"] = "query.sse.com.cn"
    page_count, total, page1 = _fetch_page(client, ann_date, 1, headers)
    out = list(page1)
    if page_count > 1:
        with ThreadPoolExecutor(max_workers=settings.CRAWL_CONCURRENCY) as ex:
            futures = {
                ex.submit(_fetch_page, client, ann_date, p, headers): p
                for p in range(2, page_count + 1)
            }
            for fut in as_completed(futures):
                try:
                    _, _, anns = fut.result()
                    out.extend(anns)
                except Exception:
                    continue  # 单页失败不拖垮整批
    if total and len(out) < total * 0.5:
        logger.warning(
            "SSE 公告可能不完整: 抓取 %d 条, 服务端 total=%d（分页或接口异常）",
            len(out), total,
        )
    out.sort(key=lambda a: (a.stock_code, a.title))
    return out
