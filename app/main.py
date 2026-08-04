"""
智能投研信息引擎 - FastAPI 后端核心主入口
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.db.mongodb import MongoDBClient
from app.api.v1 import health, insights, config, news

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("FastAPIMain")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期事件：启动时连接 MongoDB，关闭时断开"""
    logger.info("🚀 [FastAPI Core] 正在启动智能投研信息引擎后端服务...")
    db_client = MongoDBClient.get_instance()
    await db_client.connect()
    yield
    logger.info("🛑 [FastAPI Core] 正在关闭后端服务并断开数据库连接...")
    await db_client.close()


app = FastAPI(
    title="Intelligent Equity Research Engine (FastAPI Core)",
    description="智能投研信息引擎后端核心 REST API 服务",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS 跨域支持 (允许 BFF 层及前端 Vue3 访问)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API v1 路由模块
app.include_router(health.router, prefix="/api/v1")
app.include_router(insights.router, prefix="/api/v1")
app.include_router(config.router, prefix="/api/v1")
app.include_router(news.router, prefix="/api/v1")


@app.get("/", summary="根服务入口探针")
async def root_probe():
    return {
        "code": 200,
        "message": "Welcome to Intelligent Equity Research Information Engine Core API",
        "docs": "/docs",
        "health_check": "/api/v1/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
