"""
MongoDB 异步数据库驱动与连接池组件 (Motor / PyMongo)
支持 raw_news_collection, structured_news_collection, market_insight_reports 及 system_config
配置连接池大小 (maxPoolSize=50, minPoolSize=5)，集成 Loguru 日志与基准读写校验
"""
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError, BulkWriteError

from app.core.config import settings
from app.core.logger import app_logger, log_data_pipeline


class MongoDBClient:
    _instance: Optional["MongoDBClient"] = None

    def __init__(self):
        self.mongo_uri = settings.MONGODB_URI
        self.db_name = settings.MONGODB_DB_NAME
        self.max_pool_size = settings.MONGODB_MAX_POOL_SIZE
        self.min_pool_size = settings.MONGODB_MIN_POOL_SIZE
        
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        self.is_connected: bool = False

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
            app_logger.info(f"[MongoDB] 数据库连接成功！当前使用数据库: {self.db_name}")
            await self.init_indexes()
            return True
        except (ConnectionFailure, ServerSelectionTimeoutError, Exception) as e:
            self.is_connected = False
            app_logger.warning(f"[MongoDB 未开启/无法连接]: {e}")
            return False

    async def init_indexes(self):
        """初始化核心集合与索引结构 (含 365 天 TTL 自动过期清理索引)"""
        if not self.is_connected or self.db is None:
            return
        try:
            # 1. raw_news_collection 索引 (publish_time 降序索引，用于过去 24h 快讯检索)
            raw_coll = self.db["raw_news_collection"]
            await raw_coll.create_index([("publish_time", -1)])

            # 2. structured_news_collection 索引 (processed_at 降序索引与 365天 TTL 自动过期索引)
            struct_coll = self.db["structured_news_collection"]
            await struct_coll.create_index([("processed_at", -1)])
            # 365 天 = 365 * 24 * 3600 秒 = 31536000 秒
            await struct_coll.create_index(
                [("processed_at", 1)],
                expireAfterSeconds=31536000,
                name="ttl_365d_processed_at"
            )

            # 3. market_insight_reports 索引 (generation_time 降序索引，用于研报历史检索)
            report_coll = self.db["market_insight_reports"]
            await report_coll.create_index([("generation_time", -1)])

            app_logger.info("[MongoDB] 核心集合索引与 365 天 (1年) TTL 自动过期索引初始化完成！")
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
    # 数据读写操作接口
    # =========================================================================
    async def upsert_raw_news_batch(self, news_items: List[Dict[str, Any]]) -> int:
        """批量直接写入与更新原始新闻 (使用 UpdateOne Upsert 防重)"""
        if not news_items:
            return 0

        if self.is_connected and self.db is not None:
            coll = self.db["raw_news_collection"]
            operations = []
            for item in news_items:
                nid = item.get("news_id")
                if nid:
                    item_clean = dict(item)
                    operations.append(UpdateOne({"news_id": nid}, {"$set": item_clean}, upsert=True))
            if not operations:
                return 0
            try:
                res = await coll.bulk_write(operations, ordered=False)
                count = res.upserted_count + res.modified_count + res.matched_count
                log_data_pipeline("upsert_raw_news_batch", "MongoDB-RawNews", count)
                return count
            except Exception as e:
                app_logger.warning(f"MongoDB raw_news 批量 Upsert 写入提示: {e}")
                return len(news_items)
        else:
            app_logger.warning("MongoDB 未连接，原始新闻数据未落盘。")
            return 0

    async def get_raw_news_list(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最新原始新闻列表"""
        if self.is_connected and self.db is not None:
            cursor = self.db["raw_news_collection"].find({}, {"_id": 0}).sort("publish_time", -1).limit(limit)
            return await cursor.to_list(length=limit)
        return []

    async def upsert_structured_news_batch(self, card_items: List[Dict[str, Any]]) -> int:
        """批量直接写入与更新结构化情报卡片至 structured_news_collection"""
        if not card_items:
            return 0

        if self.is_connected and self.db is not None:
            coll = self.db["structured_news_collection"]
            now_dt = datetime.now(timezone.utc)
            operations = []
            for card in card_items:
                if "processed_at" not in card or not card["processed_at"]:
                    card["processed_at"] = now_dt
                elif isinstance(card["processed_at"], str):
                    try:
                        clean_pt = card["processed_at"].replace("Z", "+00:00")
                        card["processed_at"] = datetime.fromisoformat(clean_pt)
                    except Exception:
                        card["processed_at"] = now_dt
                
                nid = card.get("news_id")
                if nid:
                    operations.append(UpdateOne({"news_id": nid}, {"$set": card}, upsert=True))
                else:
                    operations.append(UpdateOne({"title": card.get("title", "")}, {"$set": card}, upsert=True))

            if not operations:
                return 0
            try:
                res = await coll.bulk_write(operations, ordered=False)
                count = res.upserted_count + res.modified_count + res.matched_count
                log_data_pipeline("upsert_structured_news_batch", "MongoDB-StructuredNews", count)
                return count
            except Exception as e:
                app_logger.warning(f"MongoDB structured_news 批量 Upsert 写入提示: {e}")
                return len(card_items)
        else:
            app_logger.warning("MongoDB 未连接，结构化情报卡片数据未落盘。")
            return 0

    async def get_structured_news_list(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """查询结构化情报卡片列表 (时间窗口下沉至数据库层，直接读取 settings.REPORT_HOURS_BACK 配置)"""
        if self.is_connected and self.db is not None:
            query = {}
            hours = settings.REPORT_HOURS_BACK
            if hours and hours > 0:
                cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
                cutoff_iso = cutoff_time.isoformat()
                query = {
                    "$or": [
                        {"processed_at": {"$gte": cutoff_time}},
                        {"processed_at": {"$gte": cutoff_iso}},
                        {"publish_time": {"$gte": cutoff_iso}},
                        {"pub_time": {"$gte": cutoff_iso}}
                    ]
                }

            cursor = self.db["structured_news_collection"].find(query, {"_id": 0}).sort("processed_at", -1)
            if limit and limit > 0:
                cursor = cursor.limit(limit)
                return await cursor.to_list(length=limit)
            return await cursor.to_list(length=None)
        return []

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
            app_logger.warning(f"MongoDB 未连接，研报 ({rid}) 未落盘。")

        return rid

    # =========================================================================
    # 择时源数据 (timing_source_data) 与 择时信号 (timing_signals_summary) MongoDB 接口
    # =========================================================================
    async def upsert_timing_source_data_batch(self, indicator_name: str, records: List[Dict[str, Any]]) -> int:
        """批量高吞吐存入原始/代理择时源数据到 MongoDB ('timing_source_data') 集合 (单次 Batch 交互)"""
        if not records:
            return 0
        if self.is_connected and self.db is not None:
            coll = self.db["timing_source_data"]
            operations = []
            for r in records:
                date_val = r.get("date") or r.get("日期") or r.get("报告日")
                if date_val:
                    r_clean = dict(r)
                    d_str = str(date_val)[:10]
                    r_clean["indicator_name"] = indicator_name
                    r_clean["date"] = d_str
                    doc_id = f"{indicator_name}_{d_str}"
                    r_clean["_id"] = doc_id
                    operations.append(UpdateOne({"_id": doc_id}, {"$set": r_clean}, upsert=True))

            if not operations:
                return 0

            res = await coll.bulk_write(operations, ordered=False)
            return res.upserted_count + res.modified_count + res.matched_count
        return 0

    async def get_max_date_timing_source(self, indicator_name: str) -> Optional[str]:
        """查询指定指标在 MongoDB 中的最大已存日期"""
        if self.is_connected and self.db is not None:
            coll = self.db["timing_source_data"]
            doc = await coll.find_one({"indicator_name": indicator_name}, sort=[("date", -1)])
            if doc and doc.get("date"):
                return str(doc.get("date"))[:10]
        return None

    async def upsert_timing_signals_batch(self, signals: List[Dict[str, Any]]) -> int:
        """批量高吞吐存入 35 项择时指标计算信号到 MongoDB ('timing_signals_summary') 集合 (单次 Batch 交互)"""
        if not signals:
            return 0
        if self.is_connected and self.db is not None:
            coll = self.db["timing_signals_summary"]
            operations = []
            for sig in signals:
                ind = sig.get("indicator")
                d_val = sig.get("effective_date") or sig.get("date")
                if ind and d_val:
                    sig_clean = dict(sig)
                    d_str = str(d_val)[:10]
                    sig_clean["date"] = d_str
                    doc_id = f"{ind}_{d_str}"
                    sig_clean["_id"] = doc_id
                    operations.append(UpdateOne({"_id": doc_id}, {"$set": sig_clean}, upsert=True))

            if not operations:
                return 0

            res = await coll.bulk_write(operations, ordered=False)
            return res.upserted_count + res.modified_count + res.matched_count
        return 0

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
        return None

    async def get_system_config(self) -> Dict[str, Any]:
        """获取当前系统订阅偏好配置"""
        default_cfg = {
            "industries": ["半导体", "人工智能"],
            "macro_keywords": ["美联储", "央行", "PMI", "关税"],
            "regions": ["国内", "美", "日", "韩"],
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        if self.is_connected and self.db is not None:
            cfg = await self.db["system_config_collection"].find_one({"config_key": "user_subscriptions"}, {"_id": 0})
            if cfg and "payload" in cfg:
                return cfg["payload"]
        return default_cfg

    async def update_system_config(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """更新系统订阅偏好配置"""
        config_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        if self.is_connected and self.db is not None:
            await self.db["system_config_collection"].update_one(
                {"config_key": "user_subscriptions"},
                {"$set": {"config_key": "user_subscriptions", "payload": config_data}},
                upsert=True
            )
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
            "mode": "mongodb_online" if self.is_connected else "disconnected",
            "batch_saved": saved_count,
            "batch_read": len(read_items),
            "elapsed_ms": round(elapsed_ms, 2)
        }
        app_logger.info(f"⚡ [Motor Benchmark]: {res}")
        return res
