"""两所公告合并去重。以 (股票代码, 标题) 为唯一键。"""
from pypinyin import lazy_pinyin

from app.stock_daily.models import Announcement


def _title_key(title: str) -> str:
    """标题排序键：按拼音（全平台确定性，与 OS locale 无关）。"""
    return "".join(lazy_pinyin(title))


def merge_announcements(
    sse_items: list[Announcement], szse_items: list[Announcement]
) -> list[Announcement]:
    seen: set[tuple[str, str]] = set()
    merged: list[Announcement] = []
    for item in list(sse_items) + list(szse_items):
        key = (item.stock_code, item.title)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    merged.sort(key=lambda a: (a.stock_code, _title_key(a.title)))
    return merged
