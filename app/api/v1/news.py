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
async def get_flash_news(limit: int = Query(50, ge=1, le=200)):
    db_client = MongoDBClient.get_instance()
    items = await db_client.get_raw_news_list(limit=limit)
    return {
        "code": 200,
        "message": "success",
        "total": len(items),
        "data": items
    }


@router.post("/fetch", summary="触发全量 28 大媒体增量快讯抓取并自动落库")
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

