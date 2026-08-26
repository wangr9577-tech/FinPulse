"""三源板块行情抓取：东财 / 新浪 / 同花顺。

统一返回 list[SectorQuote]。单源失败返回空列表（由融合层降级，不阻断整体）。
实测（2026-08-07）：同花顺被 chameleon.js 反爬拦截，fetch_ths 预留接口位直接返回空；
实际融合为东财 + 新浪两源。
"""
import json
import logging
import re
from typing import Any, Callable

import httpx

from app.stock_daily.http_client import build_headers, request_with_retry
from app.stock_daily.models import SectorQuote

logger = logging.getLogger(__name__)

# 东财板块接口：主域 push2 准实时；push2delay 延时行情作备用（实测 2026-08-07 主域
# 被 TCP 层风控拒连，delay 域稳定 200）。对「盘后 18:00 分析」场景，延时与准实时数据一致。
EASTMONEY_PATH = "/api/qt/clist/get"
EASTMONEY_BASE_URLS = [
    "https://push2.eastmoney.com",
    "https://push2delay.eastmoney.com",
]
EASTMONEY_REFERER = "https://quote.eastmoney.com/center/boardlist.html"
SINA_URL = "https://money.finance.sina.com.cn/q/view/newFLJK.php"
SINA_REFERER = "https://finance.sina.com.cn/stock/"

_FLOAT = re.compile(r"-?\d+(\.\d+)?")


def _to_float(v: Any, default: float = 0.0) -> float:
    """健壮转 float：数字/字符串/带货币符号均可；失败返回 default。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        m = _FLOAT.search(str(v))
        return float(m.group(0)) if m else default


# ---------- 东财 ----------

def _fetch_eastmoney(client: httpx.Client, fs: str, board_type: str,
                     base_url: str = EASTMONEY_BASE_URLS[0],
                     max_retries: int = 1) -> list[SectorQuote]:
    """抓东财单类板块（指定域名），分页直到拉全或空页。字段名来自 2026-08-07 实测。

    base_url 供备用域复用；max_retries 默认 1——主域被风控拒连时快速失败，
    由 fetch_eastmoney 的多域 fallback 接管（避免 3 次指数退避白等）。
    """
    out: list[SectorQuote] = []
    page = 1
    total = 0
    received = 0
    while True:
        resp = request_with_retry(
            client, "GET", base_url + EASTMONEY_PATH,
            max_retries=max_retries,
            params={
                "pn": page, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                "fid": "f3", "fs": fs,
                "fields": "f2,f3,f12,f14,f21,f62,f104,f105,f106,f128,f136,f140",
            },
            headers=build_headers(EASTMONEY_REFERER), timeout=20,
        )
        if resp.status_code != 200:
            return []
        try:
            data = resp.json().get("data") or {}
        except Exception:
            return []
        diff = data.get("diff") or []
        if not isinstance(diff, list):  # push2 部分变体返回 {"0": {...}}
            diff = diff.values() if isinstance(diff, dict) else []
        try:
            total = int(data.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        for row in diff:
            name = row.get("f14")
            if not name:
                continue
            code = str(row.get("f140") or "")
            lname = str(row.get("f128") or "")
            leaders = [f"{code} {lname}".strip()] if code and lname else []
            up = int(_to_float(row.get("f104")))
            out.append(SectorQuote(
                board_name=str(name), board_type=board_type, source="eastmoney",
                pct_change=_to_float(row.get("f3")),
                net_inflow=_to_float(row.get("f62")),
                up_count=up,
                float_market_cap=_to_float(row.get("f21")),
                total_count=up
                + int(_to_float(row.get("f105")))
                + int(_to_float(row.get("f106"))),
                leader_stocks=leaders,
            ))
            received += 1  # 只计有效行；缺 f14 的跳过行不计，避免提前终止分页
        if not diff or (total and received >= total) or page >= 20:
            if total and received < total:
                logger.warning(
                    "东财板块分页不完整: 已获取 %d/%d（可能被限流）", received, total,
                )
            break
        page += 1
    return out


def fetch_eastmoney(client: httpx.Client) -> list[SectorQuote]:
    """东财行业+概念板块，多域 fallback：主域失败快速切换备用域。

    主域 push2 被风控拒连（RemoteProtocolError，重试也救不回）时，改用
    push2delay 延时行情域兜底；两者都失败才返回空（由融合层降级）。
    """
    for base_url in EASTMONEY_BASE_URLS:
        out: list[SectorQuote] = []
        all_empty = True
        for fs, t in (("m:90+t:2+f:!50", "industry"), ("m:90+t:3+f:!50", "concept")):
            try:
                quotes = _fetch_eastmoney(client, fs, t, base_url=base_url)
                if quotes:
                    all_empty = False
                out += quotes
            except Exception as exc:
                logger.warning("东财 %s 板块抓取失败(%s): %r", base_url, t, exc)
        if not all_empty:
            return out
        logger.warning("东财 %s 无数据，切换备用域", base_url)
    return []


# ---------- 新浪 ----------

def _fetch_sina(client: httpx.Client, param: str, board_type: str) -> list[SectorQuote]:
    """抓新浪单类板块。响应为 GBK 编码 JS 变量，值为逗号分隔串。"""
    resp = request_with_retry(
        client, "GET", SINA_URL, params={"param": param},
        headers=build_headers(SINA_REFERER), timeout=20,
    )
    if resp.status_code != 200:
        return []
    m = re.search(r"\{.*\}", resp.content.decode("gbk", errors="replace"), re.S)
    if not m:
        return []
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return []
    out: list[SectorQuote] = []
    for raw in obj.values():
        parts = str(raw).split(",")
        if len(parts) < 13:
            continue
        name = parts[1]
        if not name:
            continue
        code = parts[8].strip()  # sh601118 / sz000001 / bj920019
        lname = parts[12].strip()
        leader_code = code[2:] if code[:2] in ("sh", "sz", "bj") else code
        leaders = [f"{leader_code} {lname}".strip()] if leader_code and lname else []
        out.append(SectorQuote(
            board_name=name, board_type=board_type, source="sina",
            pct_change=_to_float(parts[5]),
            net_inflow=0.0, up_count=0,  # 新浪不提供这两项
            leader_stocks=leaders,
        ))
    return out


def fetch_sina(client: httpx.Client) -> list[SectorQuote]:
    """新浪行业+概念板块。任一类失败返回已成功类。"""
    out: list[SectorQuote] = []
    for param, t in (("industry", "industry"), ("concept", "concept")):
        try:
            out += _fetch_sina(client, param, t)
        except Exception as exc:
            logger.warning("新浪板块抓取失败(%s): %r", t, exc)
    return out


# ---------- 同花顺（预留接口位） ----------

def fetch_ths(client: httpx.Client) -> list[SectorQuote]:
    """同花顺板块。当前被 chameleon.js 反爬拦截（简单 HTTP 拿不到数据），返回空。"""
    return []


# 统一注册表，供 runner 遍历
FETCHERS: list[Callable[[httpx.Client], list[SectorQuote]]] = [
    fetch_eastmoney, fetch_sina, fetch_ths,
]
