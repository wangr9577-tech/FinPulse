"""
MongoDB 异步数据库驱动与连接池组件 (Motor / PyMongo)
支持 raw_news_collection, structured_news_collection, market_insight_reports 及 system_config
配置连接池大小 (maxPoolSize=50, minPoolSize=5)，集成 Loguru 日志与基准读写校验
"""
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from app.core.logger import app_logger, log_data_pipeline


class MongoDBClient:
    _instance: Optional["MongoDBClient"] = None

    def __init__(self, mongo_uri: Optional[str] = None, db_name: Optional[str] = None):
        self.mongo_uri = mongo_uri or os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.db_name = db_name or os.getenv("MONGODB_DB_NAME", "intelligent_research_db")
        self.max_pool_size = int(os.getenv("MONGODB_MAX_POOL_SIZE", "50"))
        self.min_pool_size = int(os.getenv("MONGODB_MIN_POOL_SIZE", "5"))
        
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        self.is_connected: bool = False
        
        # 内存兜底存储 (当本地未安装或未启动 MongoDB 时保证系统可用)
        self._memory_raw_news: Dict[str, Dict[str, Any]] = {}
        self._memory_structured_news: Dict[str, Dict[str, Any]] = {}
        self._memory_reports: List[Dict[str, Any]] = []
        self._memory_config: Dict[str, Any] = {
            "industries": ["半导体", "人工智能"],
            "macro_keywords": ["美联储", "央行", "PMI", "关税"],
            "regions": ["国内", "美", "日", "韩"],
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

    @classmethod
    def get_instance(cls) -> "MongoDBClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def connect(self) -> bool:
        """建立 MongoDB 异步连接池并初始化集合与索引"""
        try:
            app_logger.info(f"正在建立 MongoDB 异步连接池 (URI: {self.mongo_uri}, maxPoolSize={self.max_pool_size})...")
            self.client = AsyncIOMotorClient(
                self.mongo_uri,
                maxPoolSize=self.max_pool_size,
                minPoolSize=self.min_pool_size,
                serverSelectionTimeoutMS=2000
            )
            # 测试 ping
            await self.client.admin.command("ping")
            self.db = self.client[self.db_name]
            self.is_connected = True
            app_logger.info(f"✅ [MongoDB] 数据库连接成功！当前使用数据库: {self.db_name}")
            await self.init_indexes()
            return True
        except (ConnectionFailure, ServerSelectionTimeoutError, Exception) as e:
            self.is_connected = False
            app_logger.warning(f"⚠️ [MongoDB 未开启/无法连接]: {e}。系统已安全切换至 Motor 内存降级缓冲模式。")
            return False

    async def init_indexes(self):
        """初始化核心集合与索引结构"""
        if not self.is_connected or self.db is None:
            return
        try:
            # 1. raw_news_collection 索引
            raw_coll = self.db["raw_news_collection"]
            await raw_coll.create_index("news_id", unique=True)
            await raw_coll.create_index([("publish_time", -1)])
            await raw_coll.create_index("source")

            # 2. structured_news_collection 索引
            struct_coll = self.db["structured_news_collection"]
            await struct_coll.create_index("raw_id")
            await struct_coll.create_index([("importance", -1)])
            await struct_coll.create_index([("processed_at", -1)])

            # 3. market_insight_reports 索引
            report_coll = self.db["market_insight_reports"]
            await report_coll.create_index("report_id", unique=True)
            await report_coll.create_index([("generation_time", -1)])

            app_logger.info("✅ [MongoDB] 核心集合索引初始化完成 (raw_news, structured_news, market_insight_reports)！")
        except Exception as e:
            app_logger.error(f"[MongoDB 索引创建失败]: {e}")

    async def close(self):
        """关闭数据库连接"""
        if self.client:
            self.client.close()
            self.client = None
            self.db = None
            self.is_connected = False
            app_logger.info("[MongoDB] 异步连接池已优雅断开。")

    # =========================================================================
    # 数据读写操作接口 (带内存降级兜底)
    # =========================================================================
    async def upsert_raw_news_batch(self, news_items: List[Dict[str, Any]]) -> int:
        """批量更新/插入原始新闻"""
        if not news_items:
            return 0

        if self.is_connected and self.db is not None:
            count = 0
            coll = self.db["raw_news_collection"]
            for item in news_items:
                nid = item.get("news_id")
                if nid:
                    res = await coll.update_one({"news_id": nid}, {"$set": item}, upsert=True)
                    if res.acknowledged:
                        count += 1
            log_data_pipeline("upsert_raw_news_batch", "MongoDB-RawNews", count)
            return count
        else:
            # 内存降级
            for item in news_items:
                nid = item.get("news_id")
                if nid:
                    self._memory_raw_news[nid] = item
            log_data_pipeline("upsert_raw_news_batch", "Memory-Fallback-RawNews", len(news_items))
            return len(news_items)

    async def get_raw_news_list(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最新原始新闻列表"""
        if self.is_connected and self.db is not None:
            cursor = self.db["raw_news_collection"].find({}, {"_id": 0}).sort("publish_time", -1).limit(limit)
            return await cursor.to_list(length=limit)
        else:
            sorted_items = sorted(
                self._memory_raw_news.values(),
                key=lambda x: str(x.get("publish_time", "")),
                reverse=True
            )
            return sorted_items[:limit]

    async def upsert_structured_news_batch(self, card_items: List[Dict[str, Any]]) -> int:
        """8月5日新增：批量更新/插入结构化情报卡片至 structured_news_collection"""
        if not card_items:
            return 0

        if self.is_connected and self.db is not None:
            count = 0
            coll = self.db["structured_news_collection"]
            for item in card_items:
                rid = item.get("raw_id")
                if rid:
                    res = await coll.update_one({"raw_id": rid}, {"$set": item}, upsert=True)
                    if res.acknowledged:
                        count += 1
            log_data_pipeline("upsert_structured_news_batch", "MongoDB-StructuredNews", count)
            return count
        else:
            # 内存降级
            for item in card_items:
                rid = item.get("raw_id")
                if rid:
                    self._memory_structured_news[rid] = item
            log_data_pipeline("upsert_structured_news_batch", "Memory-Fallback-StructuredNews", len(card_items))
            return len(card_items)

    async def get_structured_news_list(self, limit: int = 50, min_research_value: int = 1) -> List[Dict[str, Any]]:
        """8月5日新增：查询结构化情报卡片列表 (支持按研报价值筛选)"""
        if self.is_connected and self.db is not None:
            query = {"research_value": {"$gte": min_research_value}}
            cursor = self.db["structured_news_collection"].find(query, {"_id": 0}).sort("processed_at", -1).limit(limit)
            return await cursor.to_list(length=limit)
        else:
            filtered = [
                v for v in self._memory_structured_news.values()
                if v.get("research_value", 1) >= min_research_value
            ]
            sorted_items = sorted(
                filtered,
                key=lambda x: str(x.get("processed_at", "")),
                reverse=True
            )
            return sorted_items[:limit]

    async def save_insight_report(self, report_data: Dict[str, Any]) -> str:
        """保存成品研报"""
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rid = report_data.get("report_id") or f"rep_{now_str}"
        report_data["report_id"] = rid

        if self.is_connected and self.db is not None:
            coll = self.db["market_insight_reports"]
            await coll.update_one({"report_id": rid}, {"$set": report_data}, upsert=True)
            log_data_pipeline("save_insight_report", "MongoDB-Reports", 1, extra_info=rid)
        else:
            self._memory_reports.insert(0, report_data)
            log_data_pipeline("save_insight_report", "Memory-Fallback-Reports", 1, extra_info=rid)

        return rid

    # =========================================================================
    # 择时源数据 (timing_source_data) 与 择时信号 (timing_signals_summary) MongoDB 接口
    # =========================================================================
    async def upsert_timing_source_data_batch(self, indicator_name: str, records: List[Dict[str, Any]]) -> int:
        """增量存入原始/代理择时源数据到 MongoDB ('timing_source_data') 集合"""
        if not records:
            return 0
        if self.is_connected and self.db is not None:
            coll = self.db["timing_source_data"]
            count = 0
            for r in records:
                date_val = r.get("date") or r.get("日期") or r.get("报告日")
                if date_val:
                    r_clean = dict(r)
                    r_clean["indicator_name"] = indicator_name
                    r_clean["date"] = str(date_val)[:10]
                    res = await coll.update_one(
                        {"indicator_name": indicator_name, "date": r_clean["date"]},
                        {"$set": r_clean},
                        upsert=True
                    )
                    if res.acknowledged:
                        count += 1
            return count
        return len(records)

    async def get_max_date_timing_source(self, indicator_name: str) -> Optional[str]:
        """查询指定指标在 MongoDB 中的最大已存日期"""
        if self.is_connected and self.db is not None:
            coll = self.db["timing_source_data"]
            doc = await coll.find_one({"indicator_name": indicator_name}, sort=[("date", -1)])
            if doc and doc.get("date"):
                return str(doc.get("date"))[:10]
        return None

    async def upsert_timing_signals_batch(self, signals: List[Dict[str, Any]]) -> int:
        """增量存入 35 项择时指标计算信号到 MongoDB ('timing_signals_summary') 集合"""
        if not signals:
            return 0
        if self.is_connected and self.db is not None:
            coll = self.db["timing_signals_summary"]
            count = 0
            for sig in signals:
                ind = sig.get("indicator")
                d_val = sig.get("effective_date") or sig.get("date")
                if ind and d_val:
                    sig_clean = dict(sig)
                    sig_clean["date"] = str(d_val)[:10]
                    res = await coll.update_one(
                        {"indicator": ind, "date": sig_clean["date"]},
                        {"$set": sig_clean},
                        upsert=True
                    )
                    if res.acknowledged:
                        count += 1
            return count
        return len(signals)

    async def get_max_date_timing_signals(self, indicator: str) -> Optional[str]:
        """查询指定择时信号指标在 MongoDB 中的最大已存算计日期"""
        if self.is_connected and self.db is not None:
            coll = self.db["timing_signals_summary"]
            doc = await coll.find_one({"indicator": indicator}, sort=[("date", -1)])
            if doc and doc.get("date"):
                return str(doc.get("date"))[:10]
        return None

    async def get_latest_insight_report(self) -> Optional[Dict[str, Any]]:
        """获取最新的成品投研报告"""
        if self.is_connected and self.db is not None:
            report = await self.db["market_insight_reports"].find_one({}, {"_id": 0}, sort=[("generation_time", -1)])
            if report:
                return report

        if self._memory_reports:
            return self._memory_reports[0]

        return {
            "report_id": "rep_20260728_mock_01",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_industries": ["半导体", "人工智能"],
            "macro_alert": {
                "is_triggered": True,
                "events": ["国家统计局发布最新PMI数据", "美联储维持利率决议不变"]
            },
            "content_markdown": "# 行业与宏观综合研报 (7.28 LangChain + Motor 联调测试样例)\n\n## 1. 宏观货币与资金流动性\n今日全市场两融交易占比及流动性利差处于合理博弈区间，聪明钱保持净流入状态。\n\n## 2. 垂直硬科技与AI前沿\n半导体产业链晶圆产能利用率逐步回升，全球 AI 大模型生态加速商业化落地。\n\n> *本报告由智能投研信息引擎服务自动集成输出。*",
            "charts_data": {
                "margin_ratio": [
                    {"date": "2026-07-26", "value": 0.098},
                    {"date": "2026-07-27", "value": 0.102},
                    {"date": "2026-07-28", "value": 0.105}
                ]
            },
            "generation_time": datetime.now(timezone.utc).isoformat()
        }

    async def get_system_config(self) -> Dict[str, Any]:
        """获取当前系统订阅偏好配置"""
        if self.is_connected and self.db is not None:
            cfg = await self.db["system_config_collection"].find_one({"config_key": "user_subscriptions"}, {"_id": 0})
            if cfg:
                return cfg.get("payload", self._memory_config)

        return self._memory_config

    async def update_system_config(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """更新系统订阅偏好配置"""
        config_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        if self.is_connected and self.db is not None:
            await self.db["system_config_collection"].update_one(
                {"config_key": "user_subscriptions"},
                {"$set": {"config_key": "user_subscriptions", "payload": config_data}},
                upsert=True
            )

        self._memory_config = config_data
        return config_data

    async def benchmark_async_read_write(self, sample_size: int = 10) -> Dict[str, Any]:
        """7.28 专用：Motor / PyMongo 异步读写基准并发吞吐测试"""
        start_time = time.time()
        test_items = [
            {
                "news_id": f"benchmark_{i}_{int(time.time())}",
                "source": "BenchmarkTest",
                "title": f"7.28 数据库异步读写吞吐测试条目 {i}",
                "content": "Async benchmark content for Motor MongoDB pool test.",
                "publish_time": datetime.now(timezone.utc).isoformat()
            }
            for i in range(sample_size)
        ]
        
        saved_count = await self.upsert_raw_news_batch(test_items)
        read_items = await self.get_raw_news_list(limit=sample_size)
        elapsed_ms = (time.time() - start_time) * 1000

        res = {
            "mode": "mongodb_online" if self.is_connected else "memory_fallback",
            "batch_saved": saved_count,
            "batch_read": len(read_items),
            "elapsed_ms": round(elapsed_ms, 2)
        }
        app_logger.info(f"⚡ [Motor Benchmark]: {res}")
        return res
