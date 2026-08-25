"""
研报历史列表接口 (Reports History Endpoint)
为前端「总览 / 研报」页面提供历史研报列表 (标题/生成时间/PDF路径/板块数)
"""
from typing import Optional
from fastapi import APIRouter, Query

from app.db.mongodb import MongoDBClient

router = APIRouter(prefix="/reports", tags=["Insights & Reports"])


@router.get("/history", summary="获取历史研报列表 (按生成时间降序)")
async def get_report_history(limit: int = Query(20, ge=1, le=100)):
    db_client = MongoDBClient.get_instance()
    await db_client.connect()

    cursor = (
        db_client.db["market_insight_reports"]
        .find({}, {"_id": 0})
        .sort("generation_time", -1)
        .limit(limit)
    )
    items = await cursor.to_list(length=limit)

    for item in items:
        fn = item.get("file_name")
        if fn and fn.endswith(".pdf"):
            html_fn = fn.replace(".pdf", ".html")
            item["html_url"] = item.get("html_url") or f"/static/{html_fn}"
            item["pdf_url"] = item.get("pdf_url") or f"/static/{fn}"
        else:
            item["html_url"] = item.get("html_url") or "/static/market_insight_report.html"
            item["pdf_url"] = item.get("pdf_url") or "/static/market_insight_report.pdf"

    return {
        "code": 200,
        "message": "success",
        "total": len(items),
        "data": items,
    }
