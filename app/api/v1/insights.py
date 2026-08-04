"""
最新情报与综合投研研报接口 (Insights Endpoint)
匹配 TDD 5.1 协议规范: GET /api/v1/insights/latest
"""
from fastapi import APIRouter
from app.db.mongodb import MongoDBClient

router = APIRouter(prefix="/insights", tags=["Insights & Reports"])


@router.get("/latest", summary="获取最新生成的资讯研报与行情图表")
async def get_latest_insight_report():
    db_client = MongoDBClient.get_instance()
    report_data = await db_client.get_latest_insight_report()
    
    return {
        "code": 200,
        "message": "success",
        "data": report_data
    }
