# -*- coding: utf-8 -*-
"""
数据修复脚本：去重 source_data 及 cleaned_data 中的重复日期行
"""
import sys
from pathlib import Path
import pandas as pd

from app.core.config import settings

def deduplicate_csvs():
    data_dir = settings.BASE_DIR / "data"
    source_dir = data_dir / "source_data"
    cleaned_dir = data_dir / "cleaned_data"

    dirs_to_check = [source_dir, cleaned_dir]
    total_deduped = 0

    for folder in dirs_to_check:
        if not folder.exists():
            continue
        print(f"\n[检查目录] {folder}")
        csv_files = sorted(list(folder.glob("*.csv")))
        for csv_f in csv_files:
            try:
                df = pd.read_csv(csv_f, encoding="utf-8-sig")
                date_col = next((c for c in ["日期", "date", "trade_date", "stat_date"] if c in df.columns), None)
                if date_col:
                    before_len = len(df)
                    df = df.drop_duplicates(subset=[date_col], keep="last").sort_values(date_col).reset_index(drop=True)
                    after_len = len(df)
                    diff = before_len - after_len
                    if diff > 0:
                        df.to_csv(csv_f, index=False, encoding="utf-8-sig")
                        print(f"  [DEDUP] {csv_f.name}: 剔除 {diff} 条重复记录 (当前: {after_len} 条)")
                        total_deduped += diff
            except Exception as e:
                print(f"  [WARN] 处理 {csv_f.name} 出错: {e}")

    print(f"\n[完成] 共去重 {total_deduped} 条记录。")

if __name__ == "__main__":
    deduplicate_csvs()
