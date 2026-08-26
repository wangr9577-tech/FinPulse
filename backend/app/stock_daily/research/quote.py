"""候选股实时行情（东财 push2 ulist.np/get，复用 stock_names 模式）。

返回 {stock_code: 最新价 float}。请求失败/缺行情降级为空 dict，不抛出。
目标价空间 = (目标价均价 - 现价) / 现价 * 100。
"""
import logging
from typing import Any

import httpx

from app.stock_daily.http_client import build_headers, request_with_retry

logger = logging.getLogger(__name__)

ULIST_PATH = "/api/qt/ulist.np/get"
ULIST_BASE_URLS = [
    "https://push2.eastmoney.com",
    "https://push2delay.eastmoney.com",
]
ULIST_REFERER = "https://quote.eastmoney.com/center/gridlist.html"
CHUNK = 100


def _secid(code: str) -> str:
    return f"1.{code}" if code.startswith("6") else f"0.{code}"


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _fetch_chunk(client: httpx.Client, base_url: str, codes: list[str]) -> dict[str, float] | None:
    """单批查价。请求失败（非200/JSON异常）返回 None；成功但无行情返回 {}。

    返回 None 视为域名级失败（调用方切备用域）；返回 {} 视为合法空结果
    （如整批停牌无行情），不丢弃其他分块已抓到的有效价。传输异常由
    request_with_retry 抛给上层兜底。
    """
    secids = ",".join(_secid(c) for c in codes)
    resp = request_with_retry(
        client, "GET", base_url + ULIST_PATH,
        max_retries=1,
        params={"fltt": 2, "secids": secids, "fields": "f2,f12,f14"},
        headers=build_headers(ULIST_REFERER), timeout=20,
    )
    if resp.status_code != 200:
        return None
    try:
        diff = (resp.json().get("data") or {}).get("diff") or []
    except Exception:
        return None
    if not isinstance(diff, list):
        diff = diff.values() if isinstance(diff, dict) else []
    out: dict[str, float] = {}
    for row in diff:
        code = str(row.get("f12") or "")
        price = _to_float(row.get("f2"))
        if code and price > 0:
            out[code] = price
    return out


def fetch_prices(codes: list[str] | None) -> dict[str, float]:
    """批量查候选股实时价。多域 fallback，全失败降级为空 dict。"""
    codes = codes or []
    unique = sorted({c.strip() for c in codes if isinstance(c, str) and c.strip()})
    if not unique:
        return {}
    out: dict[str, float] = {}
    for base_url in ULIST_BASE_URLS:
        ok = True
        try:
            with httpx.Client(timeout=20) as client:
                for i in range(0, len(unique), CHUNK):
                    chunk = unique[i:i + CHUNK]
                    prices = _fetch_chunk(client, base_url, chunk)
                    if prices is None:  # 请求失败 → 域名级失败，切备用域
                        ok = False
                        break
                    out.update(prices)  # 合法空分块（{}）不视为失败，保留已有有效价
        except Exception as exc:
            logger.warning("行情抓取失败(%s): %r", base_url, exc)
            ok = False
        if ok and out:
            return out
        logger.warning("东财 %s 行情无有效数据，尝试备用域", base_url)
        out = {}
    logger.warning("候选股行情获取失败（全部域名无数据）")
    return out


def upside_pct(price: float, aim_l: float, aim_t: float) -> float:
    """目标价空间 %：用上下限均值；无目标价返回 0.0。"""
    if aim_l <= 0 and aim_t <= 0:
        return 0.0
    mean = (aim_l + aim_t) / 2 if aim_l > 0 and aim_t > 0 else max(aim_l, aim_t)
    if price <= 0:
        return 0.0
    return (mean - price) / price * 100.0
