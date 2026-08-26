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


# 前端「今日」口径：过去 24 小时 (从当前时间回溯)，而非自然日历日。供 is_today / today_card_count 统一使用。
TODAY_WINDOW_HOURS = 24


def _is_within_past_hours(ts: Any, hours: float = TODAY_WINDOW_HOURS) -> bool:
    """判断时间戳是否落在过去 hours 小时内 (今日 = 过去24h)。支持 datetime / ISO 字符串 / None。"""
    if ts is None:
        return False
    try:
        if isinstance(ts, datetime):
            t = ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
        else:
            clean = str(ts).replace("Z", "+00:00")
            t = datetime.fromisoformat(clean)
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return t >= cutoff


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

            # 4. daily_stock_reports 索引 (date 降序索引，用于投资日报历史检索)
            stock_coll = self.db["daily_stock_reports"]
            await stock_coll.create_index([("date", -1)])

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

    async def get_raw_news_list(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取指定时间窗口内的全量原始新闻列表 (按发布时间严格降序倒序排列)"""
        if self.is_connected and self.db is not None:
            query = {}
            hours = settings.REPORT_HOURS_BACK
            if hours and hours > 0:
                cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
                # 统一使用 datetime 比较：publish_time 在落库时已被规范为 BSON datetime。
                # 若与 ISO 字符串比较会产生 BSON 类型括号 (datetime 排序总是高于 string)，导致 24h 过滤被绕过。
                query = {"publish_time": {"$gte": cutoff_time}}
            cursor = self.db["raw_news_collection"].find(query, {"_id": 0})
            # limit=None 表示查询 24h 时间窗内全量原始新闻（供给研报流水线，不做截断）；
            # limit>0 仅用于展示类接口，保留 3 倍预取后二次截断。
            if limit and limit > 0:
                items = await cursor.to_list(length=(limit * 3))
            else:
                items = await cursor.to_list(length=None)

            def _parse_ts(it):
                pt = it.get("publish_time") or it.get("crawled_at")
                if isinstance(pt, datetime):
                    if pt.tzinfo is not None:
                        return pt.timestamp()
                    return pt.replace(tzinfo=timezone.utc).timestamp()
                if isinstance(pt, str) and pt.strip():
                    try:
                        clean_pt = pt.replace("Z", "+00:00")
                        return datetime.fromisoformat(clean_pt).timestamp()
                    except Exception:
                        pass
                return 0.0

            items.sort(key=_parse_ts, reverse=True)
            if limit and limit > 0:
                items = items[:limit]

            for it in items:
                for k in ["publish_time", "crawled_at"]:
                    if isinstance(it.get(k), datetime):
                        it[k] = it[k].isoformat()
            return items
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
                # 统一使用 datetime 比较：publish_time/processed_at 落库时已被规范为 BSON datetime。
                # 混用 ISO 字符串会产生 BSON 类型括号 (datetime 排序总是高于 string)，导致 24h 过滤失效。
                query = {
                    "$or": [
                        {"processed_at": {"$gte": cutoff_time}},
                        {"publish_time": {"$gte": cutoff_time}},
                        {"pub_time": {"$gte": cutoff_time}}
                    ]
                }

            cursor = self.db["structured_news_collection"].find(query, {"_id": 0}).sort("processed_at", -1)
            if limit and limit > 0:
                cursor = cursor.limit(limit)
                return await cursor.to_list(length=limit)
            return await cursor.to_list(length=None)
        return []

    async def get_sector_news_aggregation(self) -> List[Dict[str, Any]]:
        """按 sector 分类聚合统计结构化情报卡片 (板块名/总条数/今日新增条数/最新时间)"""
        if not (self.is_connected and self.db is not None):
            raise RuntimeError("MongoDB 未连接，无法执行板块聚合查询")
        
        coll = self.db["structured_news_collection"]

        all_cards = await coll.find({}, {"_id": 0, "sector": 1, "sub_category": 1, "publish_time": 1, "processed_at": 1}).to_list(None)
        
        sec_map: Dict[str, Dict[str, Any]] = {}
        for card in all_cards:
            sec = card.get("sector") or card.get("sub_category") or "未分类"
            if sec not in sec_map:
                sec_map[sec] = {
                    "sector": sec,
                    "_id": sec,
                    "card_count": 0,
                    "today_card_count": 0,
                    "latest_publish_time": None,
                    "latest_processed_at": None,
                }
            
            sec_map[sec]["card_count"] += 1
            
            pt = card.get("publish_time") or card.get("processed_at")
            # 今日 = 过去 24h (非自然日历日)：最近 24h 内更新过的卡片计为今日新增
            if _is_within_past_hours(pt):
                sec_map[sec]["today_card_count"] += 1
                
            pt_str = pt.isoformat() if isinstance(pt, datetime) else str(pt or "")
            if not sec_map[sec]["latest_publish_time"] or pt_str > str(sec_map[sec]["latest_publish_time"]):
                sec_map[sec]["latest_publish_time"] = pt_str
                
        rows = list(sec_map.values())
        rows.sort(key=lambda x: (x.get("today_card_count", 0), x.get("card_count", 0)), reverse=True)
        return rows

    async def get_structured_news_by_sector(
        self,
        sector: str,
        limit: Optional[int] = 100,
        hours_back: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """按板块查询结构化情报卡片 (严格按发布时间降序倒序排列，支持精确/正则/别名模糊匹配)"""
        if not (self.is_connected and self.db is not None):
            raise RuntimeError("MongoDB 未连接，无法执行板块资讯查询")

        import re
        sec_str = (sector or "").strip()

        # 别名映射与组合查询
        if sec_str in ["国内宏观", "国内", "国内宏观与金融流动性", "国内宏观与流动性"]:
            sector_filter = {"$in": ["国内宏观", "国内宏观与金融流动性", "国内宏观与流动性", "国内"]}
        elif sec_str in ["海外宏观", "国外宏观", "海外", "国外", "海外宏观与地缘政治", "全球宏观与大类资产"]:
            sector_filter = {"$in": ["海外宏观", "国外宏观", "海外宏观与地缘政治", "全球宏观与大类资产", "海外", "国外"]}
        else:
            escaped = re.escape(sec_str)
            sector_filter = {"$regex": escaped, "$options": "i"}

        query: Dict[str, Any] = {
            "$or": [
                {"sector": sector_filter},
                {"sub_category": sector_filter},
                {"category_tags": {"$in": [sec_str]}},
                {"title": {"$regex": re.escape(sec_str), "$options": "i"}}
            ]
        }

        # 仅当调用方显式传入 hours_back > 0 时才执行时间窗口硬截断，默认读取数据库最新资讯
        if hours_back and hours_back > 0:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
            time_filter = [
                {"publish_time": {"$gte": cutoff_time.isoformat()}},
                {"processed_at": {"$gte": cutoff_time}},
            ]
            query = {"$and": [query, {"$or": time_filter}]}

        # 只读结构化情报库 (全量载入候选集后统一排序，避免早期历史数据截断最新快讯)。
        # 不再兜底检索 raw_news_collection：板块标签的权威来源是 TaggerAgent 落库的结构化卡片，
        # raw_news 仅为流水线输入/暂存，其 sector 字段是抓取层的源级提示，不代表真实分类。
        cursor = self.db["structured_news_collection"].find(query, {"_id": 0})
        items = await cursor.to_list(None)

        # 严格按最新发布时间倒序排列 (最新新闻置顶)
        def _parse_ts(it):
            pt = it.get("publish_time") or it.get("processed_at") or it.get("crawled_at")
            if isinstance(pt, datetime):
                if pt.tzinfo is not None:
                    return pt.timestamp()
                return pt.replace(tzinfo=timezone.utc).timestamp()
            if isinstance(pt, str) and pt.strip():
                try:
                    clean_pt = pt.replace("Z", "+00:00")
                    return datetime.fromisoformat(clean_pt).timestamp()
                except Exception:
                    pass
            return 0.0

        # 注意：不再对查询结果做 [:limit] 前端截断，确保板块页能展示 24h 时间窗内的全量资讯。
        # 分页/展示条数由前端分页器控制，数据层返回时间窗内的完整集合。
        items.sort(key=_parse_ts, reverse=True)

        for it in items:
            for k in ["publish_time", "processed_at", "crawled_at"]:
                if isinstance(it.get(k), datetime):
                    it[k] = it[k].isoformat()
            # 标注是否为今日资讯 (今日 = 过去 24h，非自然日历日)
            it["is_today"] = _is_within_past_hours(
                it.get("publish_time") or it.get("processed_at") or it.get("crawled_at")
            )

        return items

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

    async def save_daily_stock_report(self, report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """按日期 upsert 一份投资日报 (date 唯一)。report 内含 data(date + DailyReportData JSON)。"""
        if not (self.is_connected and self.db is not None):
            return None
        date_str = report.get("date")
        if not date_str:
            return None
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        await self.db["daily_stock_reports"].update_one(
            {"date": date_str},
            {"$set": report},
            upsert=True,
        )
        return report

    async def get_daily_stock_report_latest(self) -> Optional[Dict[str, Any]]:
        """获取最新一份投资日报；无数据返回 None (前端按 available:false 空态)。"""
        if self.is_connected and self.db is not None:
            doc = await self.db["daily_stock_reports"].find_one({}, {"_id": 0}, sort=[("date", -1)])
            if doc:
                return doc
        return None

    async def get_daily_stock_report_history(self, limit: int = 30) -> List[Dict[str, Any]]:
        """获取投资日报历史 (按日期倒序，仅返回摘要字段，data 体积大不随列表返回)。"""
        if not (self.is_connected and self.db is not None):
            return []
        cursor = self.db["daily_stock_reports"].find(
            {}, {"_id": 0, "date": 1, "run_meta": 1, "generated_at": 1}
        ).sort("date", -1).limit(int(limit))
        return [doc async for doc in cursor]

    async def get_daily_stock_report_by_date(self, date_str: str) -> Optional[Dict[str, Any]]:
        """按日期精确取一份投资日报；无数据返回 None。"""
        if self.is_connected and self.db is not None:
            doc = await self.db["daily_stock_reports"].find_one({"date": date_str}, {"_id": 0})
            if doc:
                return doc
        return None

    async def get_system_config(self) -> Dict[str, Any]:
        """获取当前系统订阅偏好配置"""
        default_cfg = {
            "industries": ["半导体", "人工智能"],
            "macro_keywords": ["美联储", "央行", "PMI", "关税"],
            "regions": ["国内", "美", "日", "韩"],
            # 研报默认包含板块 (勾选配置)：研报仅分析/渲染这些板块
            "report_sectors": ["国内宏观", "国外宏观", "半导体", "互联网服务", "银行"],
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        if self.is_connected and self.db is not None:
            cfg = await self.db["system_config_collection"].find_one({"config_key": "user_subscriptions"}, {"_id": 0})
            if cfg and "payload" in cfg:
                stored = cfg["payload"]
                # 用默认值补齐旧 schema 缺失的字段 (如新加的 report_sectors)，
                # 避免历史存储的配置把新默认字段丢弃。
                merged = dict(default_cfg)
                merged.update(stored or {})
                return merged
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

    async def get_config_payload(self, config_key: str, default_payload: Dict[str, Any]) -> Dict[str, Any]:
        """读取任意配置项 (system_config_collection[{config_key}] 的 payload)。

        用 default_payload 补齐缺失字段 (仿 get_system_config 的 merge 行为)，保证历史存储缺字段时
        仍能返回完整结构；Mongo 未连接/无记录时直接返回默认值。
        """
        default_payload = dict(default_payload or {})
        if self.is_connected and self.db is not None:
            cfg = await self.db["system_config_collection"].find_one({"config_key": config_key}, {"_id": 0})
            if cfg and isinstance(cfg.get("payload"), dict):
                merged = dict(default_payload)
                merged.update(cfg["payload"])
                return merged
        return default_payload

    async def set_config_payload(self, config_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """更新任意配置项 payload，upsert 并带 updated_at 时间戳。"""
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        if self.is_connected and self.db is not None:
            await self.db["system_config_collection"].update_one(
                {"config_key": config_key},
                {"$set": {"config_key": config_key, "payload": payload}},
                upsert=True
            )
        return payload

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
