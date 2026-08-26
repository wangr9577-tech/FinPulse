"""交易日判断：SZSE monthList 接口 + 按年 CSV 缓存 + 内置静态表兜底。

规则：周末永远非交易日（先判断）；法定节假日用交易日历排除。
缓存按年存储（trade_calendar_{year}.csv），写入采用临时文件+rename 保证原子性。
若该年数据完全未知，保守返回 True（宁可爬取空数据也不漏真实交易日）。
"""
import csv
from datetime import date
from pathlib import Path

import httpx

from app.stock_daily.config import settings

MONTH_LIST_URL = "http://www.szse.cn/api/report/exchange/onepersistenthour/monthList"
_MONTH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    "Referer": "http://www.szse.cn/disclosure/listed/notice/index.html",
}


def _cache_path(year: int) -> Path:
    return settings.DATA_DIR / f"trade_calendar_{year}.csv"


def _fetch_month(client: httpx.Client, month: str) -> list[tuple[date, bool]]:
    """调用深交所交易日历接口，返回 [(日期, 是否交易日)]。"""
    resp = client.get(
        MONTH_LIST_URL, params={"month": month}, headers=_MONTH_HEADERS, timeout=15
    )
    resp.raise_for_status()
    payload = resp.json()
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    out = []
    for row in rows:
        out.append((date.fromisoformat(row["jyrq"]), str(row.get("jybz")) == "1"))
    return out


def _write_csv(path: Path, days: set[date]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["trade_date"])
        writer.writeheader()
        for d in sorted(days):
            writer.writerow({"trade_date": d.isoformat()})


def _load_csv(path: Path) -> set[date]:
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8") as f:
        return {date.fromisoformat(row["trade_date"]) for row in csv.DictReader(f)}


def _ensure_year(year: int) -> None:
    """若该年缓存文件不存在，则拉取全年并原子写入。"""
    path = _cache_path(year)
    if path.exists():
        return
    days: set[date] = set()
    with httpx.Client() as client:
        for month in range(1, 13):
            try:
                for d, is_trading in _fetch_month(client, f"{year}-{month:02d}"):
                    if is_trading:
                        days.add(d)
            except Exception:
                continue  # 单月失败继续，兜底在 is_trading_day
    tmp = path.with_suffix(".csv.tmp")
    _write_csv(tmp, days)
    tmp.rename(path)


def is_trading_day(d: date) -> bool:
    """判断某日是否 A 股交易日。未知时保守返回 True。"""
    if d.weekday() >= 5:  # 周末：确定性非交易日
        return False
    path = _cache_path(d.year)
    if not path.exists():
        try:
            _ensure_year(d.year)
        except Exception:
            pass
    cached = _load_csv(path)
    if cached:
        return d in cached
    bundled = _load_csv(settings.BUNDLED_CALENDAR)
    if bundled and any(x.year == d.year for x in bundled):
        return d in bundled
    return True  # 完全未知：保守按交易日处理
