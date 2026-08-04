"""
系统健康检查与服务探针接口 (Health Check Probe)
"""
from fastapi import APIRouter
from app.db.mongodb import MongoDBClient

router = APIRouter(prefix="/health", tags=["Health & Probe"])


@router.get("", summary="探针与健康度检查")
async def health_check():
    db_client = MongoDBClient.get_instance()
    return {
        "code": 200,
        "status": "healthy",
        "service": "Intelligent Equity Research Engine (FastAPI Core)",
        "version": "1.0.0",
        "database": {
            "connected": db_client.is_connected,
            "mode": "mongodb_online" if db_client.is_connected else "memory_fallback"
        }
    }
