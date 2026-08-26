"""深交所公告爬取：POST annList（JSON 响应）。

分页：pageSize 服务端上限 50；pageNum 从 1 起；超尾页返回空对象 {}。
"""
import math
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import httpx

from app.stock_daily.config import settings
from app.stock_daily.http_client import build_headers, request_with_retry
from app.stock_daily.models import Announcement

SZSE_URL = "https://www.szse.cn/api/disc/announcement/annList"
SZSE_REFERER = "http://www.szse.cn/disclosure/listed/notice/index.html"
SZSE_PDF_PREFIX = "https://disc.static.szse.cn/download"
PAGE_SIZE = 50


def _body(ann_date: date, page_num: int) -> dict:
    return {
        "seDate": [ann_date.isoformat(), ann_date.isoformat()],
        "channelCode": ["listedNotice_disc"],
        "pageSize": PAGE_SIZE,
        "pageNum": page_num,
    }


def _parse_row(row: dict, ann_date: date) -> Announcement:
    sec_codes = row.get("secCode") or []
    sec_names = row.get("secName") or []
    attach = row.get("attachPath") or ""
    return Announcement(
        stock_code=str(sec_codes[0]) if sec_codes else "",
        stock_name=str(sec_names[0]) if sec_names else "",
        title=str(row.get("title") or ""),
        category="",
        pdf_url=(SZSE_PDF_PREFIX + attach) if attach else "",
        exchange="SZSE",
        announce_date=ann_date,
    )


def _fetch_page(
    client: httpx.Client, ann_date: date, page_num: int, headers: dict
) -> tuple[int, list[Announcement]]:
    """抓取单页，返回 (announceCount, 本页公告)。"""
    url = f"{SZSE_URL}?random={random.random()}"
    resp = request_with_retry(
        client, "POST", url, json=_body(ann_date, page_num),
        headers=headers, timeout=20,
    )
    if resp.status_code != 200:
        return 0, []
    payload = resp.json()
    data = payload.get("data")
    if not isinstance(data, list):
        return payload.get("announceCount", 0), []
    anns = [_parse_row(row, ann_date) for row in data]
    return payload.get("announceCount", 0), [a for a in anns if a.title]


def fetch_announcements(ann_date: date, client: httpx.Client) -> list[Announcement]:
    """抓取深交所当日全部公告：首页定总页数，其余页并行拉取。"""
    headers = build_headers(SZSE_REFERER)
    headers.update({
        "Content-Type": "application/json",
        "Origin": "http://www.szse.cn",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    })
    announce_count, page1 = _fetch_page(client, ann_date, 1, headers)
    out = list(page1)
    total_pages = math.ceil(announce_count / PAGE_SIZE)
    if total_pages > 1:
        with ThreadPoolExecutor(max_workers=settings.CRAWL_CONCURRENCY) as ex:
            futures = {
                ex.submit(_fetch_page, client, ann_date, p, headers): p
                for p in range(2, total_pages + 1)
            }
            for fut in as_completed(futures):
                try:
                    _, anns = fut.result()
                    out.extend(anns)
                except Exception:
                    continue  # 单页失败不拖垮整批
    out.sort(key=lambda a: (a.stock_code, a.title))
    return out
