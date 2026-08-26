# -*- coding: utf-8 -*-
"""沪深 A 股「代码→简称」映射（补齐上交所接口缺失的股票名称）。

上交所公告接口只返回 security_Code，SECURITY_NAME 恒为 null；深交所接口自带 secName。
本模块用东财按代码批量查询接口 ulist.np/get 补齐缺失简称，供合并后 enrich 使用。

多域 fallback 与板块抓取一致：主域 push2 被风控拒连时快速切换 push2delay。
整批查询失败返回空 dict，由调用方降级（名称显示为 "-"），不阻断流程。
"""
import logging
from typing import Iterable

import httpx

from app.stock_daily.http_client import build_headers, request_with_retry

logger = logging.getLogger(__name__)

EASTMONEY_PATH = "/api/qt/ulist.np/get"
EASTMONEY_BASE_URLS = [
    "https://push2.eastmoney.com",
    "https://push2delay.eastmoney.com",
]
EASTMONEY_REFERER = "https://quote.eastmoney.com/center/gridlist.html"
CHUNK = 100  # 单请求最多带多少个 secid（实测东财 clist 页大小上限 100，ulist 同样保守取 100）


def _secid(code: str) -> str:
    """转东财 secid：6 开头=沪市(1)，其余=深市/北交所(0)。"""
    return f"1.{code}" if code.startswith("6") else f"0.{code}"


def _chunks(codes: list[str]) -> list[list[str]]:
    """按 CHUNK 切分，最多发起 ceil(n/CHUNK) 次请求。"""
    return [codes[i:i + CHUNK] for i in range(0, len(codes), CHUNK)]


def _fetch_chunk(client: httpx.Client, base_url: str, codes: list[str]) -> dict[str, str]:
    """单次批量查询一批代码，返回 {code: name}。接口异常抛错由上层兜底。"""
    out: dict[str, str] = {}
    resp = request_with_retry(
        client, "GET", base_url + EASTMONEY_PATH, max_retries=1,
        params={
            "secids": ",".join(_secid(c) for c in codes),
            "fields": "f12,f14", "fltt": "2", "invt": "2",
        },
        headers=build_headers(EASTMONEY_REFERER), timeout=20,
    )
    if resp.status_code != 200:
        return out
    data = resp.json().get("data") or {}
    diff = data.get("diff") or []
    if not isinstance(diff, list):  # push2 部分变体返回 {"0": {...}}
        diff = diff.values() if isinstance(diff, dict) else []
    for row in diff:
        code = str(row.get("f12") or "").strip()
        name = str(row.get("f14") or "").strip()
        if code and name:
            out[code] = name
    return out


def fetch_stock_names(client: httpx.Client, codes: Iterable[str]) -> dict[str, str]:
    """按代码批量查询沪深 A 股简称。返回 {code: name}；全失败返回 {}。

    多域 fallback：主域 push2 被风控拒连时快速切换 push2delay（与板块抓取一致）。
    任一分块成功即视为成功（部分缺名称不阻断）。
    """
    unique = sorted({c.strip() for c in codes if isinstance(c, str) and c.strip()})
    if not unique:
        return {}
    for base_url in EASTMONEY_BASE_URLS:
        out: dict[str, str] = {}
        ok = False
        for chunk in _chunks(unique):
            try:
                out.update(_fetch_chunk(client, base_url, chunk))
                ok = True
            except Exception as exc:
                logger.warning("东财股票名查询失败(%s, %d 码): %r", base_url, len(chunk), exc)
        if ok:
            return out
        logger.warning("东财 %s 股票名查询全失败，切换备用域", base_url)
    return {}
