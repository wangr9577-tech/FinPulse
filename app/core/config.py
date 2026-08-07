"""
系统核心全局配置文件 (backend/app/core/config.py)
用于集中管理环境变量、API 密钥、数据库连接以及研报爬取时间窗口等参数。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 自动定位与加载根目录或 backend 目录下的 .env 配置文件
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

env_path_root = PROJECT_ROOT / ".env"
env_path_backend = BACKEND_DIR / ".env"

if env_path_backend.exists():
    load_dotenv(dotenv_path=env_path_backend, override=True)
elif env_path_root.exists():
    load_dotenv(dotenv_path=env_path_root, override=True)
else:
    load_dotenv(override=True)


class Settings:
    """系统全局配置管理类"""

    BASE_DIR: Path = BACKEND_DIR
    OUTPUT_DIR: Path = BACKEND_DIR / "output"

    # 1. 研报数据分析与爬取时间窗口配置 (单位：小时)
    REPORT_HOURS_BACK: float = float(os.getenv("REPORT_HOURS_BACK"))
    CRAWL_REQUEST_TIMEOUT: float = float(os.getenv("CRAWL_REQUEST_TIMEOUT"))

    # 2. LLM 与 Agent 模型选型配置 (统一单模型)
    LLM_API_KEY: str = os.getenv("LLM_API_KEY")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL")
    LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME")
    FLASH_MODEL_NAME: str = LLM_MODEL_NAME
    PRO_MODEL_NAME: str = LLM_MODEL_NAME
    LLM_REQUEST_TIMEOUT: float = float(os.getenv("LLM_REQUEST_TIMEOUT"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES"))

    # 3. MongoDB 数据库配置
    MONGODB_URI: str = os.getenv("MONGODB_URI")
    MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME")
    MONGODB_MAX_POOL_SIZE: int = int(os.getenv("MONGODB_MAX_POOL_SIZE"))
    MONGODB_MIN_POOL_SIZE: int = int(os.getenv("MONGODB_MIN_POOL_SIZE"))

    # 4. SMTP 邮件服务配置
    SMTP_SERVER: str = os.getenv("SMTP_SERVER")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT"))
    SMTP_SENDER_EMAIL: str = os.getenv("SMTP_SENDER_EMAIL")
    SMTP_AUTH_CODE: str = os.getenv("SMTP_AUTH_CODE")
    DEFAULT_RECEIVERS: list = [r.strip() for r in os.getenv("DEFAULT_RECEIVERS").split(",") if r.strip()]

    # 5. FastAPI 服务配置
    FASTAPI_PORT: int = int(os.getenv("FASTAPI_PORT"))

    # 6. 高频新闻抓取 URL 与 RSSHub 备用节点配置
    RSSHUB_INSTANCES: list = [inst.strip() for inst in os.getenv("RSSHUB_INSTANCES").split(",") if inst.strip()]
    NEWS_SOURCE_URLS: dict = {
        "sina_7x24": os.getenv("SINA_7X24_URL"),
        "eastmoney": os.getenv("EASTMONEY_URL"),
        "36kr": os.getenv("KR36_RSS_URL"),
        "cailianpress_route": os.getenv("CAILIANPRESS_ROUTE"),
        "wallstreetcn_route": os.getenv("WALLSTREETCN_ROUTE"),
        "ithome": os.getenv("ITHOME_RSS_URL"),
        "tmtpost": os.getenv("TMTPOST_RSS_URL"),
        "eetchina_gnews": os.getenv("EETCHINA_GNEWS_URL"),
        "eetchina_route": os.getenv("EETCHINA_ROUTE"),
        "jiqizhixin_gnews": os.getenv("JIQIZHIXIN_GNEWS_URL"),
        "jiqizhixin_route": os.getenv("JIQIZHIXIN_ROUTE"),
        "qbitai_gnews": os.getenv("QBITAI_GNEWS_URL"),
        "qbitai_route": os.getenv("QBITAI_ROUTE"),
        "reuters_gnews": os.getenv("REUTERS_GNEWS_URL"),
        "reuters_route": os.getenv("REUTERS_ROUTE"),
        "bloomberg_rss": os.getenv("BLOOMBERG_RSS_URL"),
        "bloomberg_gnews": os.getenv("BLOOMBERG_GNEWS_URL"),
        "yahoofinance_rss": os.getenv("YAHOOFINANCE_RSS_URL"),
        "yahoofinance_index_rss": os.getenv("YAHOOFINANCE_INDEX_RSS_URL"),
        "jiemian_rss": os.getenv("JIEMIAN_RSS_URL"),
        "jiemian_consumer_route": os.getenv("JIEMIAN_CONSUMER_ROUTE"),
        "jiemian_invest_route": os.getenv("JIEMIAN_INVEST_ROUTE"),
        "dividend_gnews": os.getenv("DIVIDEND_GNEWS_URL"),
        "lowval_gnews": os.getenv("LOWVAL_GNEWS_URL"),
        "consumer_gnews": os.getenv("CONSUMER_GNEWS_URL"),
    }



settings = Settings()
