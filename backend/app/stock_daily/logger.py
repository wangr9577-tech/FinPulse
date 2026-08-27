"""统一日志：控制台 + 每日滚动文件。"""
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logger(name: str = "announcement", log_dir: Path | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    # 本模块自建 handler（console + 轮转文件）输出，不需要再冒泡到根 logger。
    # 根 logger 已被 app.core.logger 的 InterceptHandler 劫持（Loguru），若这里不关闭
    # propagate，同一条 pipeline 日志会同时写进自己的文件**又**灌入 Loguru，加倍放大
    # 高并发 LLM 打标时 Loguru 的队列/锁竞争（曾触发 deadlock avoided 卡死事件循环）。
    logger.propagate = False
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(FMT)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        file_handler = RotatingFileHandler(
            log_dir / f"{today}.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger
