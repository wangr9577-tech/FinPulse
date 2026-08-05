# -*- coding: utf-8 -*-
"""
MongoDBClient 接口方法单元测试脚本
验证 backend/app/db/mongodb.py 中的所有核心数据读写与查询接口
"""
import sys
import asyncio
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# 将 backend 根目录加入 PYTHONPATH 确保正常导入包
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.db.mongodb import MongoDBClient


async def run_mongodb_tests():
    print("=" * 60)
    print("🚀 [MongoDB Client 测试] 开始验证核心数据库操作接口...")
    print("=" * 60)

    db_client = MongoDBClient.get_instance()

    # 1. 测试 connect() 与 init_indexes()
    print("\n[测试 1/7] 连接数据库并初始化索引 (connect & init_indexes)...")
    is_connected = await db_client.connect()
    if not is_connected:
        print("❌ 无法连接到 MongoDB，请确保 MongoDB 服务已启动！")
        return
    print("✅ [成功] 数据库连接及索引初始化通过！")

    # 2. 测试 raw_news 读写
    print("\n[测试 2/7] 测试原始快讯接口 (upsert_raw_news_batch & get_raw_news_list)...")
    test_raw_news = [
        {
            "news_id": f"test_raw_{i}_{int(datetime.now().timestamp())}",
            "source": "UnitTest",
            "title": f"测试原始新闻标题_{i}",
            "content": f"测试原始新闻正文内容_{i}",
            "publish_time": datetime.now(timezone.utc).isoformat()
        }
        for i in range(3)
    ]
    raw_saved = await db_client.upsert_raw_news_batch(test_raw_news)
    print(f"   -> 批量写入原始新闻条数: {raw_saved}")
    raw_list = await db_client.get_raw_news_list(limit=5)
    print(f"   -> 读取最新原始新闻条数: {len(raw_list)}")
    assert raw_saved > 0, "原始新闻写入数量应 > 0"
    assert len(raw_list) > 0, "获取原始新闻列表应不为空"
    print("✅ [成功] 原始快讯接口测试通过！")

    # 3. 测试 structured_news 读写与时间窗口查询
    print("\n[测试 3/7] 测试结构化情报卡片接口 (upsert_structured_news_batch & get_structured_news_list)...")
    test_structured_cards = [
        {
            "card_id": f"test_card_{i}_{int(datetime.now().timestamp())}",
            "title": f"测试结构化卡片标题_{i}",
            "summary": f"测试核心事实摘要_{i}",
            "research_value": i + 1,
            "category_tags": ["测试板块", "人工智能"],
            "sector": "人工智能大模型",
            "processed_at": datetime.now(timezone.utc)
        }
        for i in range(3)
    ]
    struct_saved = await db_client.upsert_structured_news_batch(test_structured_cards)
    print(f"   -> 批量写入结构化卡片条数: {struct_saved}")
    cards_list = await db_client.get_structured_news_list(limit=5)
    print(f"   -> 按 env 配置时间窗口读取结构化卡片条数: {len(cards_list)}")
    assert struct_saved > 0, "结构化卡片写入数量应 > 0"
    assert len(cards_list) > 0, "获取结构化卡片列表应不为空"
    print("✅ [成功] 结构化卡片接口测试通过！")

    # 4. 测试研报保存与查询
    print("\n[测试 4/7] 测试成品研报保存与最新查询 (save_insight_report & get_latest_insight_report)...")
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    test_report = {
        "report_id": f"test_rep_{now_str}",
        "title": "单元测试成品投研报告",
        "generation_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "markdown_content": "# 测试研报\n测试正文内容。"
    }
    rep_id = await db_client.save_insight_report(test_report)
    print(f"   -> 保存成品研报 ID: {rep_id}")
    latest_report = await db_client.get_latest_insight_report()
    print(f"   -> 获取最新研报标题: {latest_report.get('title') if latest_report else 'None'}")
    assert rep_id is not None, "研报 ID 不应为空"
    assert latest_report is not None, "获取最新研报不应为空"
    print("✅ [成功] 研报保存与查询接口测试通过！")

    # 5. 测试择时源数据读写与最大日期查询
    print("\n[测试 5/7] 测试择时源数据接口 (upsert_timing_source_data_batch & get_max_date_timing_source)...")
    test_indicator = "UnitTest_Indicator"
    test_source_records = [
        {"date": "2026-08-01", "val": 100.5},
        {"date": "2026-08-02", "val": 102.3},
        {"date": "2026-08-05", "val": 105.8}
    ]
    source_count = await db_client.upsert_timing_source_data_batch(test_indicator, test_source_records)
    print(f"   -> 增量存入择时源数据记录数: {source_count}")
    max_source_date = await db_client.get_max_date_timing_source(test_indicator)
    print(f"   -> 查询指标 [{test_indicator}] 最大已存日期: {max_source_date}")
    assert source_count > 0, "择时源数据写入数应 > 0"
    assert max_source_date == "2026-08-05", f"期望最大日期为 2026-08-05，实际为 {max_source_date}"
    print("✅ [成功] 择时源数据接口测试通过！")

    # 6. 测试择时信号读写与最大日期查询
    print("\n[测试 6/7] 测试择时计算信号接口 (upsert_timing_signals_batch & get_max_date_timing_signals)...")
    test_sig_name = "UnitTest_Signal"
    test_signals = [
        {"indicator": test_sig_name, "effective_date": "2026-08-01", "signal_score": 1.5},
        {"indicator": test_sig_name, "effective_date": "2026-08-05", "signal_score": 2.0}
    ]
    sig_count = await db_client.upsert_timing_signals_batch(test_signals)
    print(f"   -> 增量存入择时信号记录数: {sig_count}")
    max_sig_date = await db_client.get_max_date_timing_signals(test_sig_name)
    print(f"   -> 查询信号 [{test_sig_name}] 最大计算日期: {max_sig_date}")
    assert sig_count > 0, "择时信号写入数应 > 0"
    assert max_sig_date == "2026-08-05", f"期望最大日期为 2026-08-05，实际为 {max_sig_date}"
    print("✅ [成功] 择时信号接口测试通过！")

    # 7. 关闭连接
    print("\n[测试 7/7] 关闭 MongoDB 连接池 (close)...")
    await db_client.close()
    print("✅ [成功] 连接已正确断开！")

    print("\n" + "=" * 60)
    print("🎉🎉🎉 [测试完成] mongodb.py 核心接口功能全部验证通过，运作正常！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_mongodb_tests())
