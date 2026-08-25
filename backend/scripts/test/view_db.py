"""
MongoDB 数据库内容可视化查看脚本
命令行直接运行: python backend/scripts/view_db.py
"""
import sys
import asyncio
from pathlib import Path

# 确保 UTF-8 控制台输出
sys.stdout.reconfigure(encoding='utf-8')

from app.db.mongodb import MongoDBClient



async def inspect_database():
    print("=================================================================")
    print("🔍 智能投研信息引擎 - MongoDB 数据库在线查验工具")
    print("=================================================================\n")

    db_client = MongoDBClient.get_instance()
    connected = await db_client.connect()

    if not connected:
        print("❌ 无法连接到本地 MongoDB 服务 (mongodb://localhost:27017)")
        return

    db = db_client.db
    print(f"✅ 已成功连接数据库: {db_client.db_name} (URI: {db_client.mongo_uri})\n")

    # 1. 统计各个集合的数据量
    raw_count = await db["raw_news_collection"].count_documents({})
    struct_count = await db["structured_news_collection"].count_documents({})
    report_count = await db["market_insight_reports"].count_documents({})

    print("📊 集合数据量汇总:")
    print(f"   - 原始新闻 (raw_news_collection): {raw_count} 条")
    print(f"   - AI情报卡片 (structured_news_collection): {struct_count} 张")
    print(f"   - 研报产出 (market_insight_reports): {report_count} 份\n")

    # 2. 查看最新 3 条 AI 结构化情报卡片
    print("-----------------------------------------------------------------")
    print("📄 最新 3 条 AI 结构化情报卡片 (structured_news_collection):")
    print("-----------------------------------------------------------------")
    cursor = db["structured_news_collection"].find({}, {"_id": 0}).sort("processed_at", -1).limit(3)
    cards = await cursor.to_list(length=3)

    if not cards:
        print("   (暂无结构化卡片数据)")
    else:
        for idx, c in enumerate(cards, 1):
            print(f"[{idx}] 标题: {c.get('title') or '无标题快讯'}")
            print(f"    - Raw ID: {c.get('raw_id')}")
            print(f"    - 来源: {c.get('source')} | 研报价值: {'⭐' * c.get('research_value', 1)} ({c.get('research_value')}星) | 冲击级别: {c.get('impact_rating')}级")
            print(f"    - 情绪: {c.get('sentiment')} (得分: {c.get('sentiment_score')})")
            print(f"    - 识别实体: {c.get('entities')}")
            print(f"    - 核心事实: {c.get('core_facts')}\n")

    await db_client.close()
    print("=================================================================")


if __name__ == "__main__":
    asyncio.run(inspect_database())
