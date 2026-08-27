# -*- coding: utf-8 -*-
"""
将 timing_source_data 中的「旧式整块 wrapped 文档」展开为规范的逐行 per-row 文档。

背景：早期 import_source_data_to_db.py 把每个数据集写成单条 wrapped 文档
(字段 = file_name + records[] + columns + row_count)，而迁移/爬虫后采用的是
逐行文档 (indicator_name + date + 各列，_id = "{indicator_name}_{date}")。
两套形状并存导致 get_timing_source_data(indicator_name) 按 indicator_name 查询时
查不到旧 wrapped 文档 —— 01_数据清洗 读不到这些种子，相关六面图指标被当作「数据
不可用」跳过，实际数据都还在。

本脚本把「尚无逐行版本」的 wrapped 文档展开成逐行文档 (与 migrate_csv_to_mongo.py 的
契约一致)，从而让 01 能读到全部种子。
- 已存在逐行文档 (indicator_name 命中且非空) 的种子会被跳过，避免用旧快照覆盖更新的逐行数据。
- 幂等：重复运行不会重复写入 (按 _id upsert)。

用法：python backend/scripts/flatten_wrapped_source_docs.py
"""
import sys
import math
import datetime
import logging
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd
from pymongo import MongoClient, UpdateOne

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402

DATE_KEYS = ["date", "日期", "月份", "报告日", "统计时间", "数据日期", "发布日期", "trade_date"]

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("FlattenWrapped")


def _pick_date_col(record: Dict[str, Any], columns: List[str]):
    for c in DATE_KEYS:
        if c in record:
            return c
    for c in columns:
        if c in record:
            return c
    return None


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    try:
        if pd.isna(v):
            return None
    except (ValueError, TypeError):
        pass
    return v


def _flatten_doc(coll, file_name: str, records: List[Dict[str, Any]]) -> int:
    """把单个 wrapped 文档的 records 展开为逐行文档并 upsert，返回写入数量。"""
    if not records:
        log.warning(f"{file_name}: records 为空，跳过")
        return 0

    date_col = _pick_date_col(records[0], list(records[0].keys()))
    if date_col is None:
        log.warning(f"{file_name}: 找不到日期列（取自 record 首键），跳过")
        date_col = list(records[0].keys())[0]

    ops = []
    for rec in records:
        date_val = rec.get(date_col)
        if date_val is None or str(date_val).strip() == "":
            continue
        d_str = str(date_val)[:10]
        row = {k: _clean(v) for k, v in rec.items()}
        row["indicator_name"] = file_name
        row["date"] = d_str
        doc_id = f"{file_name}_{d_str}"
        row["_id"] = doc_id
        ops.append(UpdateOne({"_id": doc_id}, {"$set": row}, upsert=True))

    if not ops:
        return 0
    res = coll.bulk_write(ops, ordered=False)
    n = res.upserted_count + res.modified_count + res.matched_count
    log.info(f"{file_name}: 展开 {len(ops)} 行 -> per-row (upserted={res.upserted_count})")
    return n


def main():
    client = MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=3000)
    try:
        client.admin.command("ping")
    except Exception as e:
        log.error(f"MongoDB 连接失败: {e}")
        sys.exit(1)
    db = client[settings.MONGODB_DB_NAME]
    coll = db["timing_source_data"]

    wrapped = list(coll.find({"file_name": {"$exists": True, "$ne": None}}))
    log.info(f"发现 wrapped 文档 {len(wrapped)} 条。")

    flattened = 0
    skipped = 0
    for d in wrapped:
        fn = d.get("file_name")
        # 该种子是否已有逐行文档？有则跳过，避免旧快照覆盖新逐行数据
        existing = coll.count_documents({"indicator_name": fn})
        if existing > 0:
            log.info(f"跳过 {fn} (已有逐行 {existing} 行)")
            skipped += 1
            continue
        rc = d.get("records") or []
        flattened += _flatten_doc(coll, fn, rc)

    log.info(f"DONE: 展开={flattened} 行；跳过已有逐行的种子 {skipped} 个。")
    print(f"FLATTEN_DONE rows={flattened} skipped={skipped}")


if __name__ == "__main__":
    main()
