"""
上市公司每日投资日报接口 (Stock Daily Reports)
为前端「投资日报」页面提供：手动/定时触发运行、最新一份、历史列表、按日期查询。
所有数据来自真实运行结果 (存于 Mongo daily_stock_reports)，无数据一律 available:false 空态。
"""
import asyncio
from datetime import date
from typing import Optional

from fastapi import APIRouter, Query

from app.db.mongodb import MongoDBClient
from app.stock_daily.runner import run_for_date

router = APIRouter(prefix="/stock-daily", tags=["Stock Daily Reports"])

_run_lock = asyncio.Lock()


async def _run_and_store(ann_date: date) -> dict:
    """跑一天投资日报并写入 Mongo；返回本次运行结果（供后台任务日志/前端轮询）。"""
    result = await run_for_date(ann_date)
    doc = {
        "date": result["date"],
        "report_type": "investment_daily",
        "available": result.get("available", False),
        "data": result.get("data"),
        "run_meta": result.get("run_meta"),
    }
    db_client = MongoDBClient.get_instance()
    await db_client.connect()
    await db_client.save_daily_stock_report(doc)
    return result


@router.post("/run", summary="手动/定时触发一次投资日报运行")
async def run_stock_daily(ann_date: Optional[str] = None):
    """后台运行当日（或指定日期）投资日报。默认今天；网络/Key 缺失时降级为 available:false。

    为避免长爬取阻塞 HTTP 响应，用 asyncio.create_task 后台执行，立即返回 started。
    """
    target = date.fromisoformat(ann_date) if ann_date else date.today()
    if _run_lock.locked():
        return {
            "code": 429,
            "message": "投资日报正在运行中，请稍候",
            "data": {"date": target.isoformat(), "status": "running"},
        }

    async def _task():
        async with _run_lock:
            await _run_and_store(target)

    asyncio.create_task(_task())
    return {
        "code": 200,
        "message": "已开始运行投资日报",
        "data": {"date": target.isoformat(), "status": "started"},
    }


@router.get("/latest", summary="获取最新投资日报")
async def get_stock_daily_latest():
    db_client = MongoDBClient.get_instance()
    await db_client.connect()
    doc = await db_client.get_daily_stock_report_latest()
    if not doc:
        return {
            "code": 200,
            "message": "success",
            "data": {"available": False, "date": date.today().isoformat()},
        }
    return {"code": 200, "message": "success", "data": doc}


@router.get("/history", summary="获取投资日报历史列表 (按日期降序)")
async def get_stock_daily_history(limit: int = Query(30, ge=1, le=100)):
    db_client = MongoDBClient.get_instance()
    await db_client.connect()
    items = await db_client.get_daily_stock_report_history(limit)
    return {"code": 200, "message": "success", "total": len(items), "data": items}


@router.get("/{ann_date}", summary="按日期获取投资日报")
async def get_stock_daily_by_date(ann_date: str):
    db_client = MongoDBClient.get_instance()
    await db_client.connect()
    doc = await db_client.get_daily_stock_report_by_date(ann_date)
    if not doc:
        return {
            "code": 200,
            "message": "success",
            "data": {"available": False, "date": ann_date},
        }
    return {"code": 200, "message": "success", "data": doc}
