"""
智能投研信息引擎 - FastAPI 后端核心主入口
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.db.mongodb import MongoDBClient
from app.api.v1 import health, insights, config, news, hexagon, reports, stock_daily, automation
from app.api.v1.automation import configure_scheduler, set_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("FastAPIMain")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期事件：启动时连接 MongoDB、启动每日自动运行调度器；关闭时断开并停止调度器"""
    logger.info("[FastAPI Core] 正在启动智能投研信息引擎后端服务...")
    db_client = MongoDBClient.get_instance()
    await db_client.connect()
    logger.info("[FastAPI Core] 正在启动每日自动运行调度器...")
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    # 读取配置里的 run_time，注册 cron job；默认 07:00
    cfg = await db_client.get_config_payload("daily_auto_run", {"enabled": False, "run_time": "07:00"})
    configure_scheduler(scheduler, cfg.get("run_time", "07:00"))
    set_scheduler(scheduler)
    scheduler.start()
    try:
        yield
    finally:
        logger.info("[FastAPI Core] 正在停止调度器并断开数据库连接...")
        scheduler.shutdown(wait=False)
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
app.include_router(hexagon.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(stock_daily.router, prefix="/api/v1")
app.include_router(automation.router, prefix="/api/v1")


@app.get("/api/root-probe", summary="根服务入口探针", include_in_schema=True)
async def root_probe():
    return {
        "code": 200,
        "message": "Welcome to Intelligent Equity Research Information Engine Core API",
        "docs": "/docs",
        "health_check": "/api/v1/health"
    }


# =========================================================================
# 静态资源与前端 SPA 托管
# =========================================================================
# 1. /static 挂载 backend/output (图表 PNG / PDF / HTML 研报直接访问)
output_dir = settings.OUTPUT_DIR
output_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(output_dir)), name="static")

# 2. /assets 挂载前端构建产物资源目录 (Vite 默认输出)
#    frontend/ 是 backend/ 的兄弟目录，前端 dist 位于项目根下的 frontend/dist
_frontend_dist = settings.BASE_DIR.parent / "frontend" / "dist"
_assets_dir = _frontend_dist / "assets"
if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend_spa(full_path: str):
    """前端 SPA 托管: 非 /api /static /docs 路径统一回退到 index.html (支持 Vue Router history 模式)"""
    # 先尝试直接命中 dist 下的静态文件
    if _frontend_dist.exists():
        candidate = (_frontend_dist / full_path).resolve()
        if candidate.is_file() and candidate.exists():
            return FileResponse(str(candidate))

    index_html = _frontend_dist / "index.html"
    if not index_html.exists():
        return JSONResponse(
            status_code=404,
            content={
                "code": 404,
                "message": "前端尚未构建 (frontend/dist/index.html 不存在)，请先执行 `npm run build`",
            },
        )
    return FileResponse(str(index_html))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
