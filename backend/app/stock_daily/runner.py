"""stock_daily 平台入口：把同步 pipeline 包装成可被 FastAPI / 定时脚本调用的异步函数。

外部系统 (gonggao) 的 pipeline 是同步的 (httpx 同步客户端 + 多线程)，为不阻塞
事件循环，这里用 asyncio.to_thread 包装；跑完直接返回可存 Mongo 的 JSON 字典。
"""

import asyncio
import math
from datetime import date
from typing import Any, Dict, Optional

from app.stock_daily import models
from app.stock_daily.pipeline import run_pipeline


def _rebuild_models() -> None:
    """重建 DailyReportData 的嵌套前向引用，保证 model_dump(mode="json") 可序列化。"""
    try:
        models.DailyReportData.model_rebuild()
    except Exception:
        models.DailyReportData.model_rebuild(force=True)


def _sanitize_nan(obj: Any) -> Any:
    """递归清洗非有限浮点数 (NaN/Infinity) -> None。

    板块/选股评分除零可能产生 NaN，属于非法 JSON 值，前端 JSON.parse 会直接崩，
    故在入库前统一置空（前端对 None 一律显示 '-'）。参考《前端接入规范》7(4) 坑。
    """
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


async def run_for_date(ann_date: Optional[date] = None) -> Dict[str, Any]:
    """跑一天的投资日报并返回可存 Mongo 的结果。

    返回结构:
        {"date": "YYYY-MM-DD", "available": bool, "data": {...DailyReportData JSON...}, "run_meta": {...}}

    非交易日 / 无公告 / 数据源全部失败时 data 为空字典，available=False（前端空态）。
    """
    ann_date = ann_date or date.today()
    _rebuild_models()

    # 同步 pipeline 放线程池执行，避免阻塞 async 事件循环
    data = await asyncio.to_thread(run_pipeline, ann_date)

    if not data:
        return {
            "date": ann_date.isoformat(),
            "available": False,
            "data": None,
            "run_meta": {"ann_date": ann_date.isoformat(), "status": "no_data"},
        }
    data = _sanitize_nan(data)
    return {
        "date": ann_date.isoformat(),
        "available": True,
        "data": data,
        "run_meta": {"ann_date": ann_date.isoformat(), "status": "ok"},
    }
