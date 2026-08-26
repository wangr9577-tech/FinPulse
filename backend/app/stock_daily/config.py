"""stock_daily 配置：复用 FinPulse 的 DeepSeek 密钥，其余沿用外部批处理系统默认值。

外部系统 (gonggao) 与 FinPulse 使用不同的环境变量名：
  gonggao   DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL
  FinPulse  LLM_API_KEY      / LLM_BASE_URL        / LLM_MODEL_NAME
这里统一映射到 FinPulse 的 LLM_*，**不再新增密钥**。
其余权重/阈值/路径沿用外部默认值；路径落在本包 data/ 下，可随项目整体迁移。
"""

import os
from pathlib import Path

from app.core.config import settings as finpulse

_PKG_DIR = Path(__file__).resolve().parent
_DATA_DIR = _PKG_DIR / "data"
_PDFS_DIR = _DATA_DIR / "pdfs"
_ANALYSIS_DIR = _DATA_DIR / "analysis"
_RESEARCH_PDF_DIR = _DATA_DIR / "research_pdfs"
_LOGS_DIR = _PKG_DIR / "logs"
_REPORTS_DIR = _PKG_DIR / "reports"          # 保留占位：平台不消费 docx，仅兼容外部引用
_STATE_FILE = _DATA_DIR / "state.json"       # 保留占位：平台以 Mongo upsert 幂等
_BUNDLED_CALENDAR = _DATA_DIR / "bundled_trade_days.csv"


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default)


class Settings:
    # DeepSeek（映射 FinPulse 的 LLM_* 配置；key 缺省为空，外部代码自行降级）
    DEEPSEEK_API_KEY: str = finpulse.LLM_API_KEY or ""
    DEEPSEEK_BASE_URL: str = finpulse.LLM_BASE_URL or "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = finpulse.LLM_MODEL_NAME or "deepseek-v4-flash"

    # PDF 解析 / 分析并发
    PDF_TEXT_CHARS: int = int(_get("PDF_TEXT_CHARS", "3000"))
    PDF_MIN_CHARS: int = int(_get("PDF_MIN_CHARS", "50"))
    DOWNLOAD_CONCURRENCY: int = int(_get("DOWNLOAD_CONCURRENCY", "8"))
    ANALYZE_CONCURRENCY: int = int(_get("ANALYZE_CONCURRENCY", "8"))
    CRAWL_CONCURRENCY: int = int(_get("CRAWL_CONCURRENCY", "4"))
    MAX_FULL_ANALYZE: int = int(_get("MAX_FULL_ANALYZE", "250"))
    KEEP_PDFS_AFTER_SEND: bool = _get("KEEP_PDFS_AFTER_SEND", "false").lower() == "true"

    # 路径
    DATA_DIR: Path = _DATA_DIR
    PDFS_DIR: Path = _PDFS_DIR
    ANALYSIS_DIR: Path = _ANALYSIS_DIR
    REPORTS_DIR: Path = _REPORTS_DIR
    LOGS_DIR: Path = _LOGS_DIR
    STATE_FILE: Path = _STATE_FILE
    BUNDLED_CALENDAR: Path = _BUNDLED_CALENDAR

    # 强势板块
    SECTOR_STRONG_THRESHOLD: float = float(_get("SECTOR_STRONG_THRESHOLD", "70"))
    SECTOR_MEDIUM_THRESHOLD: float = float(_get("SECTOR_MEDIUM_THRESHOLD", "40"))
    SECTOR_TOP_N_STRONG: int = int(_get("SECTOR_TOP_N_STRONG", "10"))
    SECTOR_TOP_N_MEDIUM: int = int(_get("SECTOR_TOP_N_MEDIUM", "15"))
    SECTOR_PCT_WEIGHT: float = float(_get("SECTOR_PCT_WEIGHT", "0.4"))
    SECTOR_INFLOW_WEIGHT: float = float(_get("SECTOR_INFLOW_WEIGHT", "0.4"))
    SECTOR_UPCOUNT_WEIGHT: float = float(_get("SECTOR_UPCOUNT_WEIGHT", "0.2"))
    SECTOR_RESEARCH_WEIGHT: float = float(_get("SECTOR_RESEARCH_WEIGHT", "0.2"))
    SECTOR_COMMENT_CONCURRENCY: int = int(_get("SECTOR_COMMENT_CONCURRENCY", "8"))
    REPORT_TOP_N_RECOMMEND: int = int(_get("REPORT_TOP_N_RECOMMEND", "10"))

    # 券商研报 + 每日选股
    REPORT_LOOKBACK_DAYS: int = int(_get("REPORT_LOOKBACK_DAYS", "3"))
    RESEARCH_CONCURRENCY: int = int(_get("RESEARCH_CONCURRENCY", "8"))
    RESEARCH_QA_INTERVAL: float = float(_get("RESEARCH_QA_INTERVAL", "1.0"))
    RESEARCH_PDF_DIR: Path = _RESEARCH_PDF_DIR
    PICK_MIN: int = int(_get("PICK_MIN", "3"))
    PICK_MAX: int = int(_get("PICK_MAX", "5"))
    PICK_ANN_WEIGHT: float = float(_get("PICK_ANN_WEIGHT", "0.4"))
    PICK_RATING_WEIGHT: float = float(_get("PICK_RATING_WEIGHT", "0.3"))
    PICK_PRICE_WEIGHT: float = float(_get("PICK_PRICE_WEIGHT", "0.2"))
    PICK_FRESH_WEIGHT: float = float(_get("PICK_FRESH_WEIGHT", "0.1"))
    PICK_UPSIDE_TOP: float = float(_get("PICK_UPSIDE_TOP", "0.5"))


settings = Settings()
