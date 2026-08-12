# -*- coding: utf-8 -*-
"""
一次性修复脚本：折叠 source_data 目录中的重复日期行。

背景：merge_incremental_dataframe 此前在"旧行字符串日期 vs 新行 datetime"混合时
无法去重，导致 source_data 中约半数文件堆积了约 50% 的重复行（被 01_数据清洗 的
finish_table 掩盖）。utils.py 已修复去重逻辑（去重前统一主键类型），本脚本用修好
后的同一函数对每个 source_data 文件做"自身合并"，把历史重复行折叠回唯一序列。

运行：python scripts/repair_source_data_dedup.py
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.data_fetchers.crawler.utils import (
    SOURCE_DATA,
    FILE_MAPPING_TO_SOURCE_DATA,
    merge_incremental_dataframe,
)

POSSIBLE_KEYS = ["date", "trade_date", "日期", "发布日期", "stat_month", "月份", "数据日期", "报告日", "统计时间", "报告期", "季度"]


def main() -> None:
    repaired = 0
    for f in sorted(SOURCE_DATA.glob("*.csv")):
        try:
            df = pd_read(f)
        except Exception as e:
            print(f"  [SKIP] {f.name}: {e}")
            continue

        key_cols = [c for c in POSSIBLE_KEYS if c in df.columns]
        if not key_cols:
            key_cols = [df.columns[0]]

        before = len(df)
        # 用修好的合并逻辑对自身合并：统一主键类型 -> 去重 -> 排序
        collapsed = merge_incremental_dataframe(df, df, key_cols=key_cols)
        after = len(collapsed)
        if after < before:
            collapsed.to_csv(f, index=False, encoding="utf-8-sig")
            print(f"  [OK] {f.name}: {before} -> {after} (折叠 {before - after} 行)")
            repaired += 1
        else:
            print(f"  [-] {f.name}: {before} 行，无需修复")
    print(f"\n修复完成，共折叠 {repaired} 个文件。")


def pd_read(path: Path):
    import pandas as pd
    df = pd.read_csv(path, encoding="utf-8-sig")
    df = df.dropna(how="all", axis=1)
    return df


if __name__ == "__main__":
    main()
