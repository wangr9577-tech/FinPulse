"""
自动化设置接口 (Automation Endpoint) — /api/v1/automation
========================================================================
管理「总览页两个按钮」对应的后端配置：
  GET/POST /schedule  → 每日自动运行开关 (DailyAutoRunSchema)  按钮1
  GET/POST /email     → 邮件接收设置     (ReportEmailSchema)   按钮2
  POST    /run-now    → 手动立即触发一次全量运行（便于验证）

配置持久化到 Mongo system_config_collection (config_key 分别为 daily_auto_run / report_email)。
读取 / 手动触发均不抛异常；Mongo 断开时读取返回默认值、写入落空返回内存值。
"""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.models.config_schema import DailyAutoRunSchema, ReportEmailSchema
from app.db.mongodb import MongoDBClient
from app.services.daily_auto_run import run_daily_auto, trigger_daily_auto, is_auto_run_locked, _resolve_recipients

router = APIRouter(prefix="/automation", tags=["Automation"])

JOB_ID = "daily_auto_0700"

# 调度器句柄（由 main.py lifespan 注册），供 GET /schedule 返回下次运行时间
_scheduler: AsyncIOScheduler | None = None


def set_scheduler(scheduler: AsyncIOScheduler) -> None:
    """由 main.py 在 lifespan 内注入调度器实例。"""
    global _scheduler
    _scheduler = scheduler


def _parse_run_time(run_time: str) -> tuple[int, int]:
    """解析 'HH:MM' → (hour, minute)；非法则回退 7:00。"""
    try:
        hh, mm = str(run_time).split(":")
        hour, minute = int(hh), int(mm)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except Exception:
        pass
    return 7, 0


def configure_scheduler(scheduler: AsyncIOScheduler | None, run_time: str = "07:00") -> None:
    """注册/更新每日自动运行 cron job（trigger_daily_auto）。可重复调用以刷新运行时间。"""
    if scheduler is None:
        return
    hour, minute = _parse_run_time(run_time)
    scheduler.add_job(
        trigger_daily_auto,
        "cron",
        hour=hour,
        minute=minute,
        id=JOB_ID,
        replace_existing=True,
    )


def _next_run_time() -> str | None:
    """读取已注册 cron job 的下次运行时间（ISO），未注册返回 None。"""
    if _scheduler is not None:
        try:
            job = _scheduler.get_job(JOB_ID)
            if job and job.next_run_time:
                return job.next_run_time.isoformat(timespec="seconds")
        except Exception:
            return None
    return None


def _next_run_time() -> str | None:
    """读取已注册 cron job 的下次运行时间（ISO），未注册返回 None。"""
    if _scheduler is not None:
        try:
            job = _scheduler.get_job("daily_auto_0700")
            if job and job.next_run_time:
                return job.next_run_time.isoformat(timespec="seconds")
        except Exception:
            return None
    return None


@router.get("/schedule", summary="获取每日自动运行配置")
async def get_schedule():
    db_client = MongoDBClient.get_instance()
    cfg = await db_client.get_config_payload("daily_auto_run", {"enabled": False, "run_time": "07:00"})
    cfg["next_run_time"] = _next_run_time()
    return {"code": 200, "message": "success", "data": cfg}


@router.post("/schedule", summary="更新每日自动运行配置")
async def update_schedule(payload: DailyAutoRunSchema):
    body = payload.model_dump()
    body.pop("updated_at", None)  # 由 set_config_payload 统一写入当前时间戳
    db_client = MongoDBClient.get_instance()
    saved = await db_client.set_config_payload("daily_auto_run", body)
    # 运行时间变更即时生效：重排 cron job（启用与否由 trigger_daily_auto 在触发时判断）
    configure_scheduler(_scheduler, body.get("run_time", "07:00"))
    saved["next_run_time"] = _next_run_time()
    return {"code": 200, "message": "每日自动运行配置已保存", "data": saved}


@router.get("/email", summary="获取邮件接收配置")
async def get_email():
    db_client = MongoDBClient.get_instance()
    cfg = await db_client.get_config_payload("report_email", {"enabled": False, "recipients": []})
    # 回读时把 env DEFAULT_RECEIVERS 并入前端展示（不写回 Mongo），让模态框预填 env 收件人
    cfg["recipients"] = _resolve_recipients(cfg.get("recipients") or [])
    return {"code": 200, "message": "success", "data": cfg}


@router.post("/email", summary="更新邮件接收配置")
async def update_email(payload: ReportEmailSchema):
    body = payload.model_dump()
    body.pop("updated_at", None)
    db_client = MongoDBClient.get_instance()
    saved = await db_client.set_config_payload("report_email", body)
    return {"code": 200, "message": "邮件接收配置已保存", "data": saved}


@router.post("/run-now", summary="手动立即触发一次全量运行")
async def run_now():
    """后台触发 run_daily_auto，立即返回 started。长运行不阻塞 HTTP 响应。"""
    if is_auto_run_locked():
        return {"code": 429, "message": "已有自动运行正在进行，请稍候", "data": {"status": "running"}}
    asyncio.create_task(run_daily_auto())
    return {
        "code": 200,
        "message": "已开始全量运行（资讯+六面图+公告选股）",
        "data": {"status": "started", "triggered_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
    }
