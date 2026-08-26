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
