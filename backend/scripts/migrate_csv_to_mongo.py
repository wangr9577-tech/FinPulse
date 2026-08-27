# -*- coding: utf-8 -*-
"""
一次性迁移脚本：将现有 backend/data 下的 CSV 数据导入 MongoDB ('timing_source_data')。

背景：择时六面图链路已切换为「爬虫直写 Mongo + 01/02/03 全走 Mongo」，disk 上的 CSV 即将被删除。
本脚本在删除前执行，把现有 processed/*/*.csv 与 raw/csindex/csi800 行情合并进 Mongo，
使管线在删除 CSV 后仍持有存量数据（后续增量由爬虫直写 Mongo 承接）。

写入契约与爬虫一致：_id = "{indicator_name}_{date}"，indicator_name 经 FILE_MAPPING_TO_SOURCE_DATA
映射为种子文件名（与 01_数据清洗 读取名对齐）；未命中则回退 filename。

用法：python backend/scripts/migrate_csv_to_mongo.py
"""
import sys
import datetime
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd
from pymongo import MongoClient, UpdateOne

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402

DATA_DIR = settings.BASE_DIR / "data" if (settings.BASE_DIR / "data").exists() else BACKEND / "data"
PROCESSED_DIR = DATA_DIR / "processed"
RAW_DIR = DATA_DIR / "raw"

# 复用爬虫的 processed->source_data 映射（种子文件名 = 01_数据清洗 读取名）
PROCESSED_TO_SOURCE = {
    "PE_TTM_日度.csv": "中证800PE.csv",
    "PB_日度.csv": "中证800PB.csv",
    "SHIBOR_1W_日度.csv": "SHIBOR_1W完整序列.csv",
    "DR007偏离度_日度.csv": "DR007合成代理序列.csv",
    "国债收益率10Y_日度.csv": "中国国债收益率.csv",
    "制造业PMI_月度.csv": "制造业PMI.csv",
    "CPI同比_月度.csv": "CPI.csv",
    "PPI同比_月度.csv": "PPI.csv",
    "发电量同比_月度.csv": "全社会用电量_发电量代理.csv",
    "新增开户数_月度.csv": "新增投资者.csv",
    "QVIX_日度.csv": "50ETF_QVIX.csv",
}

DATE_KEYS = ["date", "日期", "报告日", "统计时间", "月份", "数据日期", "发布日期", "trade_date"]


def _pick_date_col(df: pd.DataFrame):
    for c in DATE_KEYS:
        if c in df.columns:
            return c
    return df.columns[0] if len(df.columns) else None


def _upsert(coll, indicator_name: str, df: pd.DataFrame):
    """按 (indicator_name, date) 幂等 upsert；与爬虫契约一致。"""
    if df is None or df.empty or indicator_name is None:
        return 0, 0
    date_col = _pick_date_col(df)
    if date_col is None:
        return 0, 0
    ops = []
    for _, row in df.iterrows():
        date_val = row.get(date_col)
        if pd.isna(date_val):
            continue
        d_str = str(date_val)[:10]
        rec = {k: (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)) for k, v in row.to_dict().items()}
        rec["indicator_name"] = indicator_name
        rec["date"] = d_str
        doc_id = f"{indicator_name}_{d_str}"
        rec["_id"] = doc_id
        ops.append(UpdateOne({"_id": doc_id}, {"$set": rec}, upsert=True))
    if not ops:
        return 0, 0
    res = coll.bulk_write(ops, ordered=False)
    return res.upserted_count + res.modified_count + res.matched_count, len(ops)


def main():
    print(f"=== 存量 CSV -> MongoDB 迁移 ===\n数据目录: {DATA_DIR}")
    import os
    os.makedirs(DATA_DIR / "mongodb", exist_ok=True)  # 确保 Mongo 数据目录存在（保留）

    if not PROCESSED_DIR.exists() and not RAW_DIR.exists():
        print("[SKIP] processed/ 与 raw/ 均不存在，无存量 CSV 可迁移。")
        return

    client = MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=3000)
    try:
        client.admin.command("ping")
        print(f"[OK] MongoDB 连接成功 ({settings.MONGODB_URI})")
    except Exception as e:
        print(f"[FAIL] MongoDB 连接失败: {e}")
        sys.exit(1)
    db = client[settings.MONGODB_DB_NAME]
    coll = db["timing_source_data"]

    total_files = 0
    total_rows = 0

    # 1) processed/ 下所有 CSV -> FILE_MAPPING 种子名
    if PROCESSED_DIR.exists():
        csv_files = sorted(PROCESSED_DIR.glob("*/*.csv"))
        print(f"\n[1/2] processed/ 下共 {len(csv_files)} 个 CSV ...")
        for csv_path in csv_files:
            try:
                df = pd.read_csv(csv_path, encoding="utf-8-sig")
            except Exception as e:
                print(f"   - [略过] {csv_path.name}: 读取失败 ({e})")
                continue
            indicator_name = PROCESSED_TO_SOURCE.get(csv_path.name, csv_path.name)
            upserted, n = _upsert(coll, indicator_name, df)
            total_files += 1
            total_rows += n
            print(f"   - [已迁移] {indicator_name}  <-  {csv_path.parent.name}/{csv_path.name}  ({n} 行)")

    # 2) raw/csindex/csi800/*.csv -> 合并为「中证800日行情.csv」
    if RAW_DIR.exists():
        raw_daily = sorted((RAW_DIR / "csindex" / "csi800").glob("*.csv")) if (RAW_DIR / "csindex" / "csi800").exists() else []
        if raw_daily:
            print(f"\n[2/2] 合并 {len(raw_daily)} 个 raw/csindex/csi800 行情文件 -> 中证800日行情.csv ...")
            frames = []
            for p in raw_daily:
                try:
                    d = pd.read_csv(p, encoding="utf-8-sig")
                except Exception as e:
                    print(f"   - [略过] {p.name}: {e}")
                    continue
                frames.append(d)
            if frames:
                merged = pd.concat(frames, ignore_index=True)
                merged = merged.drop_duplicates(subset=["date"], keep="last") if "date" in merged.columns else merged
                upserted, n = _upsert(coll, "中证800日行情.csv", merged)
                total_files += 1
                total_rows += n
                print(f"   - [已迁移] 中证800日行情.csv  (~{n} 行)")

    print("\n" + "=" * 60)
    print(f"[DONE] 共迁移 {total_files} 个数据集，写入 {total_rows} 行记录 -> timing_source_data")
    print("=" * 60)


if __name__ == "__main__":
    main()
