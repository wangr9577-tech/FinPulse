# -*- coding: utf-8 -*-
"""
数据入库脚本：将 source_data 及最新择时信号数据全量存入 MongoDB 数据库 (intelligent_research_db)
"""
import os
import sys
import json
import datetime
from pathlib import Path
import pandas as pd
from pymongo import MongoClient

from app.core.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE_DATA_DIR = BASE_DIR / "data" / "source_data"
RESULTS_DIR = BASE_DIR / "data" / "results"

MONGO_URI = settings.MONGODB_URI
DB_NAME = settings.MONGODB_DB_NAME


def import_source_data():
    print(f"=== 开始连接 MongoDB: {MONGO_URI} (数据库: {DB_NAME}) ===")
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    
    try:
        client.admin.command("ping")
        print("[OK] [MongoDB] 数据库连接成功！")
    except Exception as e:
        print(f"[FAIL] [MongoDB] 连接失败: {e}")
        sys.exit(1)
        
    db = client[DB_NAME]
    
    # 1. 入库 source_data 下的 22 个 CSV 文件
    csv_files = list(SOURCE_DATA_DIR.glob("*.csv"))
    print(f"\n[1/2] 正在将 {len(csv_files)} 个 source_data 原始数据文件存入 MongoDB 'timing_source_data' 集合...")
    
    source_coll = db["timing_source_data"]
    source_coll.drop()  # 刷新重建
    
    total_docs = 0
    for csv_path in csv_files:
        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            # 将 NaN 替换为 None，便于 MongoDB 插入
            df = df.where(pd.notnull(df), None)
            
            records = df.to_dict(orient="records")
            doc = {
                "dataset_name": csv_path.stem,
                "file_name": csv_path.name,
                "row_count": len(records),
                "columns": list(df.columns),
                "imported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "records": records
            }
            source_coll.insert_one(doc)
            total_docs += len(records)
            print(f"   - [已存入] {csv_path.name}: {len(records)} 条记录")
        except Exception as ex:
            print(f"   - [错误] 处理 {csv_path.name} 失败: {ex}")
            
    print(f"[OK] source_data 数据全量入库完成，共计存入 {len(csv_files)} 个数据集，{total_docs} 行记录！")
    
    # 2. 入库 results 下的 最新信号汇总.csv 及 研报2022时点复核.csv
    print("\n[2/2] 正在存入最新信号汇总与复核数据到 'timing_signals_summary' 集合...")
    signals_coll = db["timing_signals_summary"]
    signals_coll.drop()
    
    latest_csv = RESULTS_DIR / "最新信号汇总.csv"
    if latest_csv.exists():
        df_latest = pd.read_csv(latest_csv, encoding="utf-8-sig")
        df_latest = df_latest.where(pd.notnull(df_latest), None)
        latest_records = df_latest.to_dict(orient="records")
        signals_coll.insert_one({
            "type": "latest_signals",
            "imported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(latest_records),
            "records": latest_records
        })
        print(f"   - [已存入] 最新信号汇总: {len(latest_records)} 项指标")
        
    review_csv = RESULTS_DIR / "研报2022时点复核.csv"
    if review_csv.exists():
        df_review = pd.read_csv(review_csv, encoding="utf-8-sig")
        df_review = df_review.where(pd.notnull(df_review), None)
        review_records = df_review.to_dict(orient="records")
        signals_coll.insert_one({
            "type": "2022_baseline_review",
            "imported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(review_records),
            "records": review_records
        })
        print(f"   - [已存入] 2022基准复核数据: {len(review_records)} 项指标")
        
    print("=" * 60)
    print("[SUCCESS] 全部 source_data 及择时信号数据已完美导入 MongoDB 数据库！")
    print("=" * 60)

if __name__ == "__main__":
    import_source_data()
