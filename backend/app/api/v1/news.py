"""
高频快讯与增量新闻数据接口 (News Flash API)
"""
from typing import Optional
from fastapi import APIRouter, Query
from app.core.config import settings
from app.db.mongodb import MongoDBClient
from app.data_fetchers.flash_news_fetcher import FlashNewsFetcher

router = APIRouter(prefix="/news", tags=["News Data"])


@router.get("/flash", summary="查询最新增量资讯与高频快讯列表")
async def get_flash_news(limit: int = Query(50, ge=0, le=5000, description="0 表示返回 24h 时间窗内全量，不做截断")):
    db_client = MongoDBClient.get_instance()
    # 只读结构化情报库：板块标签的权威来源是 TaggerAgent 落库结果，
    # raw_news 仅为流水线输入/暂存（其 sector 是抓取层源级提示，不代表真实分类）。
    items = await db_client.get_structured_news_list(limit=(limit if limit and limit > 0 else None))
    return {
        "code": 200,
        "message": "success",
        "total": len(items),
        "data": items
    }


@router.get("/sectors", summary="按板块聚合统计资讯 (板块名/总条数/今日新增条数/最新时间)")
async def get_sector_news_aggregation():
    db_client = MongoDBClient.get_instance()
    await db_client.connect()
    rows = await db_client.get_sector_news_aggregation()

    sectors = []
    for row in rows:
        sectors.append({
            "sector": row.get("sector") or row.get("_id"),
            "card_count": row.get("card_count", 0),
            "today_card_count": row.get("today_card_count", 0),
            "latest_publish_time": row.get("latest_publish_time"),
            "latest_processed_at": row.get("latest_processed_at"),
        })

    return {
        "code": 200,
        "message": "success",
        "total": len(sectors),
        "data": sectors
    }


@router.get("/by_sector", summary="按板块查询资讯列表 (时间降序)")
async def get_news_by_sector(
    sector: str = Query(..., description="板块名称，如 半导体与芯片"),
    limit: int = Query(0, ge=0, le=5000, description="0 表示返回 24h 时间窗内该板块全量资讯，不做截断"),
    hours_back: Optional[float] = Query(None, description="时间窗口(小时)，默认取系统配置")
):
    db_client = MongoDBClient.get_instance()
    await db_client.connect()
    items = await db_client.get_structured_news_by_sector(
        sector=sector,
        limit=(limit if limit and limit > 0 else None),
        hours_back=hours_back
    )
    return {
        "code": 200,
        "message": "success",
        "sector": sector,
        "total": len(items),
        "data": items
    }


@router.post("/fetch", summary="触发全量 16 大媒体增量快讯抓取并自动落库")
async def trigger_fetch_news():
    fetcher = FlashNewsFetcher()
    news_items = await fetcher.fetch_all_flash_news()
    
    # 转换为 dict 落库
    raw_dicts = [item.model_dump(mode="json") for item in news_items]
    db_client = MongoDBClient.get_instance()
    saved_count = await db_client.upsert_raw_news_batch(raw_dicts)

    return {
        "code": 200,
        "message": f"成功拉取过去 {settings.REPORT_HOURS_BACK} 小时内 {len(news_items)} 条增量快讯，更新落库 {saved_count} 条记录",
        "fetched_total": len(news_items),
        "saved_total": saved_count
    }

