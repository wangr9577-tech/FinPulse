"""统一 HTTP 请求层：headers 助手、超时、指数退避重试（移植 flash_news_fetcher 模式）。"""
import random
import time
from typing import Any

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def build_headers(referer: str = "") -> dict[str, str]:
    """生成标准请求头（参考 flash_news_fetcher._get_headers）。"""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, text/xml, application/xml, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_retries: int = 3,
    retry_base: float = 1.5,
    **kwargs: Any,
) -> httpx.Response:
    """带指数退避重试的请求。网络异常或 5xx 重试；成功或 4xx 直接返回。

    重试耗尽仍失败则抛出最后一次异常，由调用方兜底。
    """
    attempt = 0
    while True:
        try:
            resp = client.request(method, url, **kwargs)
            if resp.status_code < 500 or attempt >= max_retries:
                return resp
        except httpx.HTTPError:
            if attempt >= max_retries:
                raise
        attempt += 1
        time.sleep(min(2 ** attempt, 15) * retry_base + random.random())
