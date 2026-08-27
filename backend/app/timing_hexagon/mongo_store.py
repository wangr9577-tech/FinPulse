# -*- coding: utf-8 -*-
"""
择时六面图 DataFrame <-> MongoDB 桥接层 (MongoStore)
====================================================
统一规范 key：
- timing_source_data      : indicator_name = 种子文件名(含 .csv)，如 "中证800日行情.csv"
- timing_cleaned_data     : indicator_name = 清洗后文件名(含 .csv)，如 "中证800日行情_清洗后.csv"
- timing_indicator_outputs: indicator_name = 指标结果文件名(含 .csv)，category = indicator_outputs / proxy_outputs
- timing_signals_summary  : indicator（沿用 02 现有写法）

同步/异步桥接：01/02/03/plotter 与爬虫均以**独立子进程**运行 (pipeline.py / run_all.py 用 subprocess
调度)，进程内无运行中的事件循环；而 MongoDBClient 基于 Motor(async)。考虑到 Motor 客户端与 asyncio.run
创建的 loop 绑定、跨 loop 复用会导致 "attached to different loop" 错误，这里**每个操作自成一次
asyncio.run，内部 connect -> 操作 -> close**，循环内不跨函数复用。

缺数据降级：读取时若 Mongo 无该 indicator 的数据、或 Mongo 不可用，返回 None（调用方据此跳过对应
六面图条目，而非中断整条流水线——符合「读到就读，读不到就把这一项删掉」的产品意图）。
"""
import asyncio
import math
from datetime import date as _date, datetime as _datetime
from typing import Optional, List, Dict, Any

import pandas as pd

from app.db.mongodb import MongoDBClient

# 供各脚本日志统一使用 (脚本自行 config basicConfig)
import logging
logger = logging.getLogger("MongoStore")


def _run(coro):
    """在独立事件循环中执行异步协程。

    调用方通常是脚本 (独立子进程，无运行中 loop)，直接用 asyncio.run。
    但本桥接层也可能被**异步上下文**复用——如 LangGraph 的 node_aggregate 节点、
    FastAPI 的 async 路由在运行中的事件循环里同步调用 load_* 时，asyncio.run 会抛
    'Cannot run event loop while another loop is running'。上层 get_timing_hexagon_summary
    会 try/except 吞掉它，导致择时六面图汇总被**静默丢失** (而非崩溃)，因此这里必须兜住。

    处理：检测到已存在运行中 loop 时，把 asyncio.run 挪到**独立子线程**里执行，
    经 join + 变量回传结果。每个操作仍自成一次 fresh loop，Motor 客户端不与该 loop
    复用绑定，符合本模块「每操作一个 asyncio.run」的既有设计。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        return asyncio.run(coro)

    # 已在运行中的 loop 内：在子线程里跑独立 asyncio.run，避免跨循环/嵌套循环冲突
    import threading

    box: dict = {}
    error: dict = {}

    def _worker():
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001  原样回抛给调用方
            error["exc"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error["exc"]
    return box["value"]


def _norm_name(indicator_name: str) -> str:
    """确保 key 以 .csv 结尾 (便于与前文的种子/结果文件名对齐)。"""
    name = str(indicator_name)
    if name.lower().endswith(".csv"):
        return name
    return f"{name}.csv"


def _clean_bson(v):
    """把 pandas 的 NaN / NaT、以及纯日期 (datetime.date，非 datetime) 等 BSON-unencodable
    值规范化，避免 bulk_write 报 'NaTType does not support utcoffset' / 无法编码 date 而整批丢弃。"""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    # akshare 原始帧常把日期列返回为 Python 原生 date (如 margin 的 '日期'、基金的 '报告期')，
    # BSON 无法直接编码 date，统一转为 datetime 便于落库，供 01 用 pd.to_datetime 解析。
    if isinstance(v, _date) and not isinstance(v, _datetime):
        try:
            return _datetime(v.year, v.month, v.day)
        except Exception:
            return None
    try:
        if pd.isna(v):
            return None
    except (ValueError, TypeError):
        pass
    return v


def _sanitize_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """逐字段清理记录，确保可写入 Mongo (Motor/bson)。"""
    return [{k: _clean_bson(val) for k, val in rec.items()} for rec in records]


async def _connect() -> Optional[MongoDBClient]:
    db = MongoDBClient()
    ok = await db.connect()
    if not ok:
        logger.warning("MongoStore: MongoDB 未连接，读取/写入将返回空。")
        return None
    return db


# ---------------------------------------------------------------------------
# 读取：返回 DataFrame，缺数据返回 None
# ---------------------------------------------------------------------------
def load_source_frame(indicator_name: str) -> Optional[pd.DataFrame]:
    """读取择时原始/代理源数据序列；缺失/空返回 None。"""
    name = _norm_name(indicator_name)

    async def _op() -> Optional[List[Dict[str, Any]]]:
        db = await _connect()
        if db is None:
            return None
        try:
            return await db.get_timing_source_data(name)
        finally:
            await db.close()

    docs = _run(_op())
    if not docs:
        logger.warning(f"MongoStore: {name} 源数据缺失或为空，跳过该项。")
        return None
    df = pd.DataFrame.from_records(docs)
    if df.empty:
        return None
    return df


def load_cleaned_frame(indicator_name: str) -> Optional[pd.DataFrame]:
    """读取清洗后的数据序列；缺失/空返回 None。"""
    name = _norm_name(indicator_name)

    async def _op() -> Optional[List[Dict[str, Any]]]:
        db = await _connect()
        if db is None:
            return None
        try:
            return await db.get_timing_cleaned_data(name)
        finally:
            await db.close()

    docs = _run(_op())
    if not docs:
        logger.warning(f"MongoStore: {name} 清洗后数据缺失或为空，跳过该项。")
        return None
    df = pd.DataFrame.from_records(docs)
    if df.empty:
        return None
    return df


def load_indicator_frame(indicator_name: str) -> Optional[pd.DataFrame]:
    """读取某个指标结果文件全序列；缺失/空返回 None。"""
    name = _norm_name(indicator_name)

    async def _op() -> Optional[List[Dict[str, Any]]]:
        db = await _connect()
        if db is None:
            return None
        try:
            return await db.get_timing_indicator_outputs(name)
        finally:
            await db.close()

    docs = _run(_op())
    if not docs:
        logger.warning(f"MongoStore: {name} 指标输出缺失或为空，跳过该项。")
        return None
    df = pd.DataFrame.from_records(docs)
    if df.empty:
        return None
    return df


def load_signals_summary() -> Optional[pd.DataFrame]:
    """读取择时信号汇总全序列 (供前端六面图 + 03 校验)。"""

    async def _op() -> Optional[List[Dict[str, Any]]]:
        db = await _connect()
        if db is None:
            return None
        try:
            return await db.get_timing_signals_summary()
        finally:
            await db.close()

    docs = _run(_op())
    if not docs:
        logger.warning("MongoStore: timing_signals_summary 无数据。")
        return None
    return pd.DataFrame.from_records(docs)


# ---------------------------------------------------------------------------
# 写入：DataFrame -> Mongo upsert
# ---------------------------------------------------------------------------
def save_source_frame(indicator_name: str, df: pd.DataFrame, incremental: bool = True) -> int:
    """写入源数据。incremental=True 时先读已有并去重合并，keep='last' 覆盖旧值。"""
    name = _norm_name(indicator_name)
    if df is None or df.empty:
        return 0

    merged = df
    if incremental:
        existing = load_source_frame(name)
        if existing is not None and not existing.empty:
            combined = pd.concat([existing, df], ignore_index=True)
            key = "date" if "date" in combined.columns else combined.columns[0]
            # 保留新抓取记录
            merged = combined.drop_duplicates(subset=[key], keep="last")

    records = _sanitize_records(merged.to_dict(orient="records"))

    async def _op() -> int:
        db = await _connect()
        if db is None:
            return 0
        try:
            return await db.upsert_timing_source_data_batch(name, records)
        finally:
            await db.close()

    count = _run(_op())
    logger.info(f"MongoStore: 源数据 {name} 写入 {len(records)} 行 (upsert {count})。")
    return count


def save_cleaned_frame(indicator_name: str, df: pd.DataFrame) -> int:
    """写入清洗后数据。"""
    name = _norm_name(indicator_name)
    if df is None or df.empty:
        return 0
    records = _sanitize_records(df.to_dict(orient="records"))

    async def _op() -> int:
        db = await _connect()
        if db is None:
            return 0
        try:
            return await db.upsert_timing_cleaned_data_batch(name, records)
        finally:
            await db.close()

    count = _run(_op())
    logger.info(f"MongoStore: 清洗后 {name} 写入 {len(records)} 行。")
    return count


def save_indicator_frame(indicator_name: str, category: str, df: pd.DataFrame) -> int:
    """写入指标结果文件 (category = indicator_outputs / proxy_outputs)。"""
    name = _norm_name(indicator_name)
    if df is None or df.empty:
        return 0
    records = _sanitize_records(df.to_dict(orient="records"))

    async def _op() -> int:
        db = await _connect()
        if db is None:
            return 0
        try:
            return await db.upsert_timing_indicator_outputs_batch(name, category, records)
        finally:
            await db.close()

    count = _run(_op())
    logger.info(f"MongoStore: 指标输出 [{category}] {name} 写入 {len(records)} 行。")
    return count


def save_signals_summary(df: pd.DataFrame) -> int:
    """写入择时信号汇总（整表替换，见 upsert 前的 delete）。

    汇总语义为「最新截面快照，每指标一行」：02 的 add_latest 每指标只取一行 latest，
    故每次运行整表重写最干净——先清空旧行再 upsert 本期行，避免同一指标多行累积
    （增量 upsert 在有效日期前移时会旧行残留，破坏 03 的"25项且名称唯一"校验）。
    """
    if df is None or df.empty:
        return 0
    records = _sanitize_records(df.to_dict(orient="records"))

    async def _op() -> int:
        db = await _connect()
        if db is None:
            return 0
        try:
            await db.delete_timing_signals_summary()
            return await db.upsert_timing_signals_batch(records)
        finally:
            await db.close()

    count = _run(_op())
    logger.info(f"MongoStore: 择时信号汇总整表重写 {len(records)} 行。")
    return count
