# -*- coding: utf-8 -*-
"""
高频快讯与增量新闻抓取引擎独立测试与调度脚本 (backend/scripts/test_flash_news_fetcher.py)
用于手动测试 FlashNewsFetcher 数据抓取或独立命令行执行。
"""
import sys
import asyncio
from pathlib import Path

# 确保 UTF-8 控制台输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.data_fetchers.flash_news_fetcher import FlashNewsFetcher



async def main():
    fetcher = FlashNewsFetcher()
    print(f"🚀 开始测试 28 大媒体增量快讯抓取 (时间窗口: {fetcher.max_hours}h, 超时: {fetcher.request_timeout}s)...")
    items = await fetcher.fetch_all_flash_news()
    print(f"✅ 抓取完成！共整合 {len(items)} 条增量唯一资讯卡片。")
    if items:
        print("\n--- 最新 3 条快讯示例 ---")
        for i, item in enumerate(items[:3], 1):
            print(f"{i}. [ID: {item.news_id}] [{item.source}] {item.title} ({item.publish_time})")


if __name__ == "__main__":
    asyncio.run(main())
