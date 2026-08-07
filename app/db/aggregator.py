"""
按板块标签直接分组模块 (SectorGrouper)
取消复杂的物理聚类计算，直接依据新闻卡片自带的固定 Sector 分类标签进行字典分组。
"""
from typing import Dict, List, Optional, Any
from app.core.logger import app_logger, log_data_pipeline
from app.db.mongodb import MongoDBClient


class SectorGrouper:
    """
    按板块分类分组器：直接按 card['sector'] 标签将新闻卡片进行字典分组
    """
    def __init__(self, db_client: Optional[MongoDBClient] = None):
        self.db_client = db_client or MongoDBClient.get_instance()

    async def group_by_sector(self) -> Dict[str, Dict[str, Any]]:
        """
        直接读取 MongoDB 中时间窗口内的结构化卡片，并按 sector 分类标签纯字典分组
        """
        all_cards = await self.db_client.get_structured_news_list()
        
        sector_groups: Dict[str, Dict[str, Any]] = {}

        for card in all_cards:
            sector_name = card.get("sector") or "其他板块"
            if sector_name not in sector_groups:
                sector_groups[sector_name] = {
                    "sector_name": sector_name,
                    "card_count": 0,
                    "cards": []
                }
            sector_groups[sector_name]["cards"].append(card)
            sector_groups[sector_name]["card_count"] += 1

        log_data_pipeline("group_by_sector", "SectorGrouper", len(all_cards), extra_info=f"Active Sectors: {list(sector_groups.keys())}")
        app_logger.info(f"✅ [SectorGrouper] 按板块分类分组完成！共包含 {len(sector_groups)} 个板块 ({list(sector_groups.keys())})")
        return sector_groups
