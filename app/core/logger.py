"""
统一日志封装模块 (Loguru Logger Integration)
负责整个数据抓取、文本清洗、Data Agent 初筛及 Analyst Agent 研报生成的流转日志记录
"""
import sys
import logging
from pathlib import Path
from loguru import logger

# 确保日志输出目录存在
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "app_pipeline.log"


class InterceptHandler(logging.Handler):
    """
    将 Python 标准 logging 模块的日志记录拦截并转发重定向给 Loguru
    以实现 FastAPI, Uvicorn, Motor, HTTPX 等日志风格的统一
    """
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logger():
    """初始化并配置全局 Loguru 日志输出风格与轮转策略"""
    # 移除默认 handler
    logger.remove()

    # 1. 控制台彩化输出配置
    logger.add(
        sys.stdout,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
        enqueue=True,
    )

    # 2. 文件日志输出配置 (带按天/文件大小自动切割轮转与保存)
    logger.add(
        str(LOG_FILE),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="7 days",
        encoding="utf-8",
        enqueue=True,
    )

    # 3. 拦截标准 logging 日志 (FastAPI / Uvicorn / PyMongo 等)
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for logger_name in ("uvicorn", "uvicorn.access", "fastapi", "httpx", "motor"):
        mod_logger = logging.getLogger(logger_name)
        mod_logger.handlers = [InterceptHandler()]

    logger.info("✅ [Loguru Logger] 统一流转日志引擎初始化完成 (终端控制台 + 本地日志文件 `logs/app_pipeline.log`)")
    return logger


def log_data_pipeline(action: str, source: str, count: int, extra_info: str = ""):
    """数据采集与清洗流转专用日志记录器"""
    msg = f"🔄 [Data Pipeline] Action: {action} | Source: {source} | Count: {count}"
    if extra_info:
        msg += f" | Info: {extra_info}"
    logger.info(msg)


def log_agent_action(agent_name: str, status: str, details: str):
    """Agent 运行逻辑专用日志记录器"""
    logger.info(f"🤖 [{agent_name}] Status: {status} | Details: {details}")


# 暴露单例 logger 供全局直接使用
app_logger = setup_logger()
