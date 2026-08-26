"""
每日自动运行编排器 (app/services/daily_auto_run.py)
========================================================================
在 FastAPI 进程内以子进程方式运行「全部内容」：
  1. 资讯 LangGraph + 择时六面图：scripts/run_end_to_end_pipeline.py
  2. 公告选股 (每日投资日报)：scripts/run_stock_daily.py
随后：
  3. 取最新投资日报并渲染 Markdown → compile_report_to_pdf 生成 daily_report.pdf
  4. 收集 output/ 下所有研报 PDF (market_insight_report / timing_report / daily_report)
  5. 读 report_email 配置，启用且有收件人时 send_report_email 一并发送

为什么用子进程：run_end_to_end_pipeline 内部用 asyncio.run 且失败 sys.exit(1)，
不能直接在当前 FastAPI 事件循环里调用，必须以子进程隔离 (PYTHONPATH=backend, cwd=backend)。

设计约束：每一步单独 try/except，单步失败只记日志、不阻断后续，**绝不向调度循环抛出**；
也不生成/编造任何数据（子进程本就按空态降级）。
"""
import asyncio
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logger import app_logger
from app.db.mongodb import MongoDBClient
from app.services.email_sender import send_report_email

BACKEND_DIR = settings.BASE_DIR
SCRIPTS_DIR = BACKEND_DIR / "scripts"  # 与 main.py 位置约定一致 (backend/scripts)

# 主研报固定文件名（run_end_to_end_pipeline 实际产物）
_NEWS_PDF = settings.OUTPUT_DIR / "market_insight_report.pdf"
_TIMING_PDF = settings.OUTPUT_DIR / "timing_report.pdf"
_DAILY_PDF = settings.OUTPUT_DIR / "daily_report.pdf"

# 并发重跑守卫：同一时刻只允许一个自动运行
_run_lock = asyncio.Lock()


def is_auto_run_locked() -> bool:
    """是否已有自动运行在进行中（供 HTTP 层快速判断，避免 create_task 重复排队）。"""
    return _run_lock.locked()


def _subprocess_env() -> dict:
    """构造子进程环境：确保 backend 在 PYTHONPATH，脚本可 import app.*。"""
    env = dict(os.environ)
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(BACKEND_DIR) + (os.pathsep + pythonpath if pythonpath else "")
    return env


async def _run_script(script_name: str, args: Optional[list[str]] = None) -> dict:
    """以子进程跑一个 backend/scripts 下的脚本，返回 {"ok", "returncode", "tail"}."""
    script = SCRIPTS_DIR / script_name
    cmd = [sys.executable, str(script)] + (args or [])
    app_logger.info(f"[AUTO] 启动子进程: {' '.join(cmd)}")
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(BACKEND_DIR),
            env=_subprocess_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=None,
        )
        tail = (proc.stdout or "")[-800:] + ((proc.stderr or "")[-800:] if proc.stderr else "")
        ok = proc.returncode == 0
        app_logger.info(f"[AUTO] 子进程 {script_name} → exit={proc.returncode} {'OK' if ok else 'FAIL'}")
        if not ok:
            app_logger.error(f"[AUTO] {script_name} 失败: {tail}")
        return {"ok": ok, "returncode": proc.returncode, "tail": tail}
    except Exception as exc:
        app_logger.error(f"[AUTO] 启动子进程 {script_name} 异常: {exc!r}")
        return {"ok": False, "returncode": None, "tail": str(exc)}


async def _render_daily_pdf(ann_date: Optional[str]) -> bool:
    """取最新投资日报，渲染 Markdown 并编译成 daily_report.pdf。"""
    try:
        db_client = MongoDBClient.get_instance()
        await db_client.connect()
        doc = None
        if ann_date:
            doc = await db_client.get_daily_stock_report_by_date(ann_date)
        if not doc:
            doc = await db_client.get_daily_stock_report_latest()
        if not doc or not doc.get("available"):
            app_logger.warning("[AUTO] 无可用投资日报数据，跳过 daily_report.pdf 渲染。")
            return False
        from app.stock_daily.report_render import render_daily_report_markdown
        md = render_daily_report_markdown(doc.get("data") or {})
        from scripts.convert_report_to_pdf import compile_report_to_pdf
        await compile_report_to_pdf(
            md,
            str(_DAILY_PDF),
            base_name="daily_report",
            display_label="每日投资日报",
            report_type=None,
        )
        return _DAILY_PDF.exists()
    except Exception as exc:
        app_logger.error(f"[AUTO] 渲染 daily_report.pdf 失败: {exc!r}")
        return False


def _collect_attachments() -> List[Path]:
    """收集存在的主研报附件，按 importance 顺序。"""
    att = []
    for p in (_NEWS_PDF, _TIMING_PDF, _DAILY_PDF):
        if p.exists():
            att.append(p)
    if not att and settings.OUTPUT_DIR.exists():
        # 兜底：取 output 目录下最新的 pdf
        pdfs = sorted(settings.OUTPUT_DIR.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True)
        att = pdfs[:1]
    app_logger.info(f"[AUTO] 收集到附件 {len(att)} 个: {[p.name for p in att]}")
    return att


def _resolve_recipients(config_recipients: List[str]) -> List[str]:
    """解析收件人列表：以 .env 的 DEFAULT_RECEIVERS 为基准，并入配置里的额外收件人，去重。

    「收件人邮箱从 env 读取」：sender 逻辑始终把 env 配置的 DEFAULT_RECEIVERS 作为默认收件人，
    前端按钮填的邮箱作为补充并集（少于此情况也能发到 env 收件人）。
    """
    env_rcv = [r.strip() for r in (settings.DEFAULT_RECEIVERS or []) if r and r.strip()]
    cfg_rcv = [r.strip() for r in (config_recipients or []) if r and r.strip()]
    seen, out = set(), []
    for r in env_rcv + cfg_rcv:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


async def _send_email(attachments: List[Path], date_str: str) -> dict:
    """读 report_email 配置，启用且有收件人时发送。收件人从 env DEFAULT_RECEIVERS 读取。"""
    try:
        db_client = MongoDBClient.get_instance()
        cfg = await db_client.get_config_payload("report_email", {"enabled": False, "recipients": []})
        if not cfg.get("enabled"):
            app_logger.info("[AUTO] 邮件发送未启用，跳过。")
            return {"enabled": False, "sent": False, "receivers": []}
        recipients = _resolve_recipients(cfg.get("recipients") or [])
        if not recipients:
            app_logger.info("[AUTO] 邮件已启用但无收件人（env 与配置均为空），跳过。")
            return {"enabled": True, "sent": False, "receivers": []}
        subject = f"[智能投研日报] 每日全量研报 ({date_str})"
        ok = send_report_email(receivers=recipients, subject=subject, pdf_paths=attachments, html_paths=None)
        return {"enabled": True, "sent": ok, "receivers": recipients}
    except Exception as exc:
        app_logger.error(f"[AUTO] 邮件发送异常: {exc!r}")
        return {"enabled": True, "sent": False, "receivers": [], "error": str(exc)}


async def run_daily_auto(ann_date: Optional[str] = None) -> Dict[str, Any]:
    """跑一遍全部内容并返回汇总 dict。绝不向调用方抛出。

    返回:
      {
        "triggered_at": iso, "ann_date": str|None,
        "news": {...subprocess result...},
        "stock_daily": {...subprocess result...},
        "daily_pdf": bool, "attachments": [names], "email": {...}
      }
    """
    triggered_at = datetime.now().isoformat(timespec="seconds")
    if _run_lock.locked():
        app_logger.warning("[AUTO] 存在并发自动运行，本次跳过。")
        return {"triggered_at": triggered_at, "ann_date": ann_date, "skipped": True}

    async with _run_lock:
        ann_date = ann_date or date.today().isoformat()
        app_logger.info(f"[AUTO] 开始每日自动运行，日期: {ann_date}")

        news_res = await _run_script("run_end_to_end_pipeline.py", args=[])
        stock_daily_res = await _run_script(
            "run_stock_daily.py",
            args=["--date", ann_date] if ann_date else [],
        )

        daily_pdf = await _render_daily_pdf(ann_date)
        attachments = _collect_attachments()
        email_res = await _send_email(attachments, ann_date)

        summary = {
            "triggered_at": triggered_at,
            "ann_date": ann_date,
            "news": news_res,
            "stock_daily": stock_daily_res,
            "daily_pdf": daily_pdf,
            "attachments": [p.name for p in attachments],
            "email": email_res,
            "skipped": False,
        }
        app_logger.info(f"[AUTO] 每日自动运行完成: {summary}")
        return summary


async def trigger_daily_auto() -> None:
    """APScheduler cron job 处理器：读 daily_auto_run 开关，开启才跑。

    该函数永不抛出，内部任何失败都只记日志。7:00 跑公告选股时当日公告多未发布，
    子进程会按 available:false 空态降级，不产生编造数据。
    """
    try:
        db_client = MongoDBClient.get_instance()
        cfg = await db_client.get_config_payload("daily_auto_run", {"enabled": False, "run_time": "07:00"})
        if not cfg.get("enabled"):
            app_logger.info("[AUTO] 每日自动运行未启用（daily_auto_run.enabled=False），本次跳过。")
            return
        app_logger.info("[AUTO] 触发每日自动运行...")
        await run_daily_auto()
    except Exception as exc:
        app_logger.error(f"[AUTO] 每日自动运行 job 异常（已吞掉，不影响调度器）: {exc!r}")
