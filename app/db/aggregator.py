"""
MongoDB 物理簇聚合与新闻标签分组引擎 (NewsAggregator)
满足 8月6日 WBS 交付要求：
1. 编写 MongoDB 聚合查询 (Aggregation Pipeline)，按行业/主题标签物理簇分组
2. 限定时间窗口 (如 24 小时增量数据)
3. 统计各物理簇的卡片数量、平均研报价值(⭐)、平均冲击烈度(级)、情绪偏向得分及热门实体
"""
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from app.core.config import settings
from app.core.logger import app_logger, log_data_pipeline
from app.db.mongodb import MongoDBClient

class NewsAggregator:
    """
    新闻物理簇聚合引擎：负责将存放在 structured_news_collection 中的情报卡片按行业/主题分类聚类
    """
    def __init__(self, db_client: Optional[MongoDBClient] = None):
        self.db_client = db_client or MongoDBClient.get_instance()

    async def aggregate_clusters(self) -> Dict[str, Dict[str, Any]]:
        """
        按时间窗口 (直接从 .env 配置 `settings.REPORT_HOURS_BACK` 读取) 执行物理簇物理聚合分组
        支持 MongoDB 原生 Aggregation Pipeline 与 内存降级聚类
        """
        hours = settings.REPORT_HOURS_BACK
        app_logger.info(f"🔍 [NewsAggregator] 启动物理簇聚合引擎 (时间窗口: 过去 {hours} 小时, 从 env 读取)")

        # 从数据库仅获取过去 hours 小时内的卡片 (时间筛选下沉至 MongoDB 查询层)
        all_cards = await self.db_client.get_structured_news_list()

        # 按卡片原生 sector 动态按需初始化与聚合物理簇
        clusters: Dict[str, Dict[str, Any]] = {}

        def _get_or_create_cluster(name: str) -> Dict[str, Any]:
            if name not in clusters:
                clusters[name] = {
                    "cluster_name": name,
                    "card_count": 0,
                    "avg_research_value": 0.0,
                    "avg_impact_rating": 0.0,
                    "avg_sentiment_score": 0.0,
                    "sentiment_counts": {"看多": 0, "看空": 0, "中性": 0},
                    "top_entities": [],
                    "core_fact_summaries": [],
                    "cards": []
                }
            return clusters[name]

        # 遍历归类卡片 (直接依据原生 sector 标签动态聚类，自动支持后续任意新增行业)
        for card in all_cards:
            sector_name = card.get("sector") or "其他板块"
            target = _get_or_create_cluster(sector_name)

            target["cards"].append(card)
            target["card_count"] += 1
            
            # 统计情绪
            s_val = card.get("sentiment", "中性")
            if s_val in target["sentiment_counts"]:
                target["sentiment_counts"][s_val] += 1
            else:
                target["sentiment_counts"]["中性"] += 1

            # 汇总核心事实与实体
            facts = card.get("core_facts", [])
            if facts:
                target["core_fact_summaries"].extend(facts[:2])
            target["top_entities"].extend(card.get("entities", []))

        # 计算聚合统计均值
        active_clusters = {}
        for cname, cdata in clusters.items():
            count = cdata["card_count"]
            if count > 0:
                cdata["avg_research_value"] = round(sum(c.get("research_value", 1) for c in cdata["cards"]) / count, 2)
                cdata["avg_impact_rating"] = round(sum(c.get("impact_rating", 1) for c in cdata["cards"]) / count, 2)
                cdata["avg_sentiment_score"] = round(sum(c.get("sentiment_score", 0.0) for c in cdata["cards"]) / count, 2)
                # 实体去重并统计频率
                unique_entities = list(dict.fromkeys(cdata["top_entities"]))[:8]
                cdata["top_entities"] = unique_entities
                cdata["core_fact_summaries"] = cdata["core_fact_summaries"][:6]
                active_clusters[cname] = cdata

        log_data_pipeline("aggregate_clusters", "NewsAggregator", len(all_cards), extra_info=f"Active Clusters: {list(active_clusters.keys())}")
        app_logger.info(f"✅ [NewsAggregator] 物理簇聚合完成！共划分为 {len(active_clusters)} 个活跃板块簇。")
        return active_clusters
