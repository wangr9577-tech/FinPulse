"""
板块维度工具 (sector_utils)
1. 宏观/海外板块别名展开：把前端「研报板块勾选」的展示标签映射为数据库中真实存在的 sector 别名集合。
2. 同事件去重的标题归一化：对新闻标题做「去标点/去空白/去括号括注/去来源后缀」的轻量归并，识别重复事件。
"""
import re
from typing import List, Set

# 东财行业 + 宏观别名组 (与 mongodb.py 的别名映射保持一致)
MACRO_CN_ALIASES: List[str] = ["国内宏观", "国内", "国内宏观与金融流动性", "国内宏观与流动性"]
MACRO_GL_ALIASES: List[str] = [
    "海外宏观", "国外宏观", "海外", "国外",
    "海外宏观与地缘政治", "全球宏观与大类资产",
]

# 常见的新闻来源后缀 (去重时作为噪声剔除)
_SOURCE_SUFFIXES: List[str] = [
    "财联社", "新浪财经", "东方财富", "华尔街见闻", "界面新闻", "澎湃新闻",
    "每经网", "每日经济新闻", "证券时报", "中国证券报", "上海证券报", "21世纪经济报道",
    "36氪", "36kr", "IT之家", "IT168", "钛媒体", "虎嗅", "机器之心", "量子位",
    "智东西", "电子工程专辑", "集微网", "科创板日报",
    "Reuters", "Bloomberg", "YahooFinance", "Reuters, Bloomberg", "新闻晨报",
]

# 归一化时被剔除的标点 / 连接符
_PUNCT_RE = re.compile(
    r"[\s　"          # 空白 + 全角空格
    r"，。！？、；：,.!?;:·•"
    r"'“”‘’\""
    r"（）\(\)\[\]【】<>《》「」『』"
    r"\-—_/\\|+&=#@%^*~`"
    r"]*"
)

# 括号括注 (通常为来源/作者/时效标记)，整体剔除
_PAREN_RE = re.compile(r"[（(\[【][^）)\]】]*[）)\]】]")


def normalize_title(title: str) -> str:
    """对标题做归一化，用于识别「同事件/近重」新闻。"""
    if not title:
        return ""
    t = title.strip().lower()
    t = _PAREN_RE.sub("", t)          # 去掉括号括注
    t = _PUNCT_RE.sub("", t)          # 去掉标点/空白/连接符
    # 去掉尾部来源后缀
    for suf in _SOURCE_SUFFIXES:
        if t.endswith(suf.lower()):
            t = t[: -len(suf)].rstrip()
    return t


def expand_sector_selection(selected: List[str]) -> Set[str]:
    """
    将「研报板块勾选」的展示标签展开为数据库真实 sector 别名集合。
    - 非宏观板块：仅返回该标签自身。
    - 国内宏观 / 国外宏观：展开为其全部别名，保证别名命中的卡片都能被纳入。
    """
    expanded: Set[str] = set()
    for label in selected or []:
        label = (label or "").strip()
        if not label:
            continue
        if label in MACRO_CN_ALIASES or label == "国内宏观":
            expanded.update(MACRO_CN_ALIASES)
        elif label in MACRO_GL_ALIASES or label in ["国外宏观", "海外宏观"]:
            expanded.update(MACRO_GL_ALIASES)
        else:
            expanded.add(label)
    return expanded
