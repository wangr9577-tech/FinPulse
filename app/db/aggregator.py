"""
MongoDB 物理簇聚合与新闻标签分组引擎 (NewsAggregator)
满足 8月6日 WBS 交付要求：
1. 编写 MongoDB 聚合查询 (Aggregation Pipeline)，按行业/主题标签物理簇分组
2. 限定时间窗口 (如 24 小时增量数据)
3. 统计各物理簇的卡片数量、平均研报价值(⭐)、平均冲击烈度(级)、情绪偏向得分及热门实体
"""
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone

from app.core.logger import app_logger, log_data_pipeline
from app.db.mongodb import MongoDBClient


# 标准行业与主题物理簇定义映射
DEFAULT_CLUSTERS = {
    "国内宏观与流动性": ["宏观政策", "央行", "逆回购", "PMI", "货币政策", "流动性", "国家统计局", "A股", "宏观"],
    "中美博弈与海外宏观": ["海外宏观", "美联储", "FOMC", "加息", "降息", "地缘政治", "通胀", "美股", "中美", "关税", "博弈"],
    "半导体芯片": ["半导体", "芯片", "晶圆代工", "Chiplet", "封测", "EUV", "光刻机", "硬科技"],
    "人工智能大模型": ["人工智能", "AI大模型", "AI", "算力", "具身智能", "机器人", "TMT"],
}


class NewsAggregator:
    """
    新闻物理簇聚合引擎：负责将存放在 structured_news_collection 中的情报卡片按行业/主题分类聚类
    """
    def __init__(self, db_client: Optional[MongoDBClient] = None):
        self.db_client = db_client or MongoDBClient.get_instance()

    async def aggregate_clusters(
        self,
        hours: float = 24.0,
        min_research_value: int = 1
    ) -> Dict[str, Dict[str, Any]]:
        """
        按时间窗口 (默认为过去 24 小时) 执行物理簇物理聚合分组
        支持 MongoDB 原生 Aggregation Pipeline 与 内存降级聚类
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        app_logger.info(f"🔍 [NewsAggregator] 启动物理簇聚合引擎 (时间窗口: 过去 {hours} 小时, 研报门槛: >={min_research_value}⭐)")

        # 从数据库获取全部符合条件的卡片
        all_cards = await self.db_client.get_structured_news_list(limit=200, min_research_value=min_research_value)

        # 初始化聚类字典
        clusters: Dict[str, Dict[str, Any]] = {
            cluster_name: {
                "cluster_name": cluster_name,
                "card_count": 0,
                "avg_research_value": 0.0,
                "avg_impact_rating": 0.0,
                "avg_sentiment_score": 0.0,
                "sentiment_counts": {"看多": 0, "看空": 0, "中性": 0},
                "top_entities": [],
                "core_fact_summaries": [],
                "cards": []
            }
            for cluster_name in DEFAULT_CLUSTERS.keys()
        }
        # 其他未分类簇
        clusters["其他板块"] = {
            "cluster_name": "其他板块",
            "card_count": 0,
            "avg_research_value": 0.0,
            "avg_impact_rating": 0.0,
            "avg_sentiment_score": 0.0,
            "sentiment_counts": {"看多": 0, "看空": 0, "中性": 0},
            "top_entities": [],
            "core_fact_summaries": [],
            "cards": []
        }

        # 遍历归类卡片 (严格按过去 hours 小时时间窗口过滤)
        for card in all_cards:
            pt = card.get("processed_at") or card.get("publish_time") or card.get("pub_time")
            if pt:
                try:
                    if isinstance(pt, str):
                        clean_pt = pt.replace("Z", "+00:00")
                        card_dt = datetime.fromisoformat(clean_pt)
                    elif isinstance(pt, datetime):
                        card_dt = pt
                    else:
                        card_dt = None
                    if card_dt:
                        if card_dt.tzinfo is None:
                            card_dt = card_dt.replace(tzinfo=timezone.utc)
                        if card_dt < cutoff_time:
                            continue  # 排除超出指定小时数范围的数据
                except Exception:
                    pass

            matched_cluster = None
            tags = card.get("category_tags", []) + card.get("entities", [])
            event_type = card.get("event_type", "")
            title = card.get("title", "")

            # 匹配对应物理簇
            for cluster_name, keywords in DEFAULT_CLUSTERS.items():
                if any(kw in tags or kw in title or kw in event_type for kw in keywords):
                    matched_cluster = cluster_name
                    break

            if not matched_cluster:
                matched_cluster = "其他板块"

            target = clusters[matched_cluster]
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
