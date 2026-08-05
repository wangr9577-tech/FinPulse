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

if env_path_root.exists():
    load_dotenv(dotenv_path=env_path_root)
elif env_path_backend.exists():
    load_dotenv(dotenv_path=env_path_backend)
else:
    load_dotenv()


class Settings:
    """系统全局配置管理类"""

    # 1. 研报数据分析与爬取时间窗口配置 (单位：小时，默认 24.0h)
    REPORT_HOURS_BACK: float = float(os.getenv("REPORT_HOURS_BACK", os.getenv("CRAWL_MAX_HOURS", "24.0")))
    CRAWL_REQUEST_TIMEOUT: float = float(os.getenv("CRAWL_REQUEST_TIMEOUT", "12.0"))

    # 2. LLM 与 Agent 模型选型配置
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    FLASH_MODEL_NAME: str = os.getenv("FLASH_MODEL_NAME", "deepseek-v4-flash")
    PRO_MODEL_NAME: str = os.getenv("PRO_MODEL_NAME", "deepseek-v4-flash")

    # 3. MongoDB 数据库配置
    MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME", "intelligent_research_db")
    MONGODB_MAX_POOL_SIZE: int = int(os.getenv("MONGODB_MAX_POOL_SIZE", "50"))
    MONGODB_MIN_POOL_SIZE: int = int(os.getenv("MONGODB_MIN_POOL_SIZE", "5"))

    # 4. SMTP 邮件服务配置
    SMTP_SERVER: str = os.getenv("SMTP_SERVER", "smtp.qq.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "465"))
    SMTP_SENDER_EMAIL: str = os.getenv("SMTP_SENDER_EMAIL", "")
    SMTP_AUTH_CODE: str = os.getenv("SMTP_AUTH_CODE", "")
    DEFAULT_RECEIVERS: list = [r.strip() for r in os.getenv("DEFAULT_RECEIVERS", "").split(",") if r.strip()]

    # 5. FastAPI 服务配置
    FASTAPI_PORT: int = int(os.getenv("FASTAPI_PORT", "8000"))

    # 6. 高频新闻抓取 URL 与 RSSHub 备用节点配置
    RSSHUB_INSTANCES: list = [
        inst.strip() for inst in os.getenv(
            "RSSHUB_INSTANCES",
            "https://rsshub.rssforever.com,https://rsshub.app,https://rss.hub.maipdf.com"
        ).split(",") if inst.strip()
    ]
    NEWS_SOURCE_URLS: dict = {
        "sina_7x24": os.getenv("SINA_7X24_URL", "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=50&zhibo_id=152"),
        "eastmoney": os.getenv("EASTMONEY_URL", "https://newsapi.eastmoney.com/kuaixun/v2/api/list?pageSize=50&pageIndex=1"),
        "36kr": os.getenv("KR36_RSS_URL", "https://36kr.com/feed"),
        "cailianpress_route": os.getenv("CAILIANPRESS_ROUTE", "/cls/telegraph"),
        "wallstreetcn_route": os.getenv("WALLSTREETCN_ROUTE", "/wallstreetcn/live/global"),
        "ithome": os.getenv("ITHOME_RSS_URL", "https://www.ithome.com/rss/"),
        "tmtpost": os.getenv("TMTPOST_RSS_URL", "https://www.tmtpost.com/rss"),
        "eetchina_gnews": os.getenv("EETCHINA_GNEWS_URL", "https://news.google.com/rss/search?q=%E7%94%B5%E5%AD%90%E5%B7%A5%E7%A8%8B%E4%B8%93%E8%BE%91+when:24h&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"),
        "eetchina_route": os.getenv("EETCHINA_ROUTE", "/eetchina/news"),
        "jiqizhixin_gnews": os.getenv("JIQIZHIXIN_GNEWS_URL", "https://news.google.com/rss/search?q=%E6%9C%BA%E5%99%A8%E4%B9%8B%E5%BF%83+when:24h&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"),
        "jiqizhixin_route": os.getenv("JIQIZHIXIN_ROUTE", "/jiqizhixin"),
        "qbitai_gnews": os.getenv("QBITAI_GNEWS_URL", "https://news.google.com/rss/search?q=%E9%87%8F%E5%AD%90%E4%BD%8D+when:24h&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"),
        "qbitai_route": os.getenv("QBITAI_ROUTE", "/qbitai"),
        "reuters_gnews": os.getenv("REUTERS_GNEWS_URL", "https://news.google.com/rss/search?q=site:reuters.com+when:24h&hl=en-US&gl=US&ceid=US:en"),
        "reuters_route": os.getenv("REUTERS_ROUTE", "/reuters/world"),
        "bloomberg_rss": os.getenv("BLOOMBERG_RSS_URL", "https://feeds.bloomberg.com/markets/news.rss"),
        "bloomberg_gnews": os.getenv("BLOOMBERG_GNEWS_URL", "https://news.google.com/rss/search?q=site:bloomberg.com+when:24h&hl=en-US&gl=US&ceid=US:en"),
        "yahoofinance_rss": os.getenv("YAHOOFINANCE_RSS_URL", "https://finance.yahoo.com/news/rssindex"),
        "yahoofinance_index_rss": os.getenv("YAHOOFINANCE_INDEX_RSS_URL", "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US"),
        "jiemian_rss": os.getenv("JIEMIAN_RSS_URL", "https://www.jiemian.com/rss"),
        "jiemian_consumer_route": os.getenv("JIEMIAN_CONSUMER_ROUTE", "/jiemian/list/32"),
        "jiemian_invest_route": os.getenv("JIEMIAN_INVEST_ROUTE", "/jiemian/list/114"),
        "dividend_gnews": os.getenv("DIVIDEND_GNEWS_URL", "https://news.google.com/rss/search?q=%E9%AB%98%E8%82%A1%E6%81%AF+OR+%E7%BA%A2%E5%88%A9+when:24h&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"),
        "lowval_gnews": os.getenv("LOWVAL_GNEWS_URL", "https://news.google.com/rss/search?q=%E7%A0%B4%E5%87%80+OR+%E4%BD%8E%E4%BC%B0%E5%80%BC+OR+%E8%82%A1%E4%BB%BD%E5%9B%9E%E8%B4%AD+when:24h&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"),
        "consumer_gnews": os.getenv("CONSUMER_GNEWS_URL", "https://news.google.com/rss/search?q=%E5%A4%A7%E6%B6%88%E8%B4%B9+OR+%E7%99%BD%E9%85%92+OR+%E9%A3%9F%E5%93%81%E9%A5%AE%E6%96%99+OR+%E9%9B%B6%E5%94%AE%E6%B6%88%E8%B4%B9+when:24h&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"),
    }



settings = Settings()
