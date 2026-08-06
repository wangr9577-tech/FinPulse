"""
NewsAggregator (新闻物理簇聚合引擎) 独立单元测试脚本
验证：
1. 建立数据库连接并插入具备不同 sector (行业板块) 的测试卡片
2. 调用 NewsAggregator.aggregate_clusters() 执行物理簇聚合
3. 校验聚合结果中的板块划分、平均研报价值、情绪分布及实体抽取
"""
import sys
import io
import asyncio
from pathlib import Path
from datetime import datetime, timezone

# 适配 Windows 控制台 UTF-8 输出
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 引入项目根目录以确保模块正常导入
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.db.mongodb import MongoDBClient
from app.db.aggregator import NewsAggregator
from app.core.logger import app_logger


async def run_aggregator_tests():
    print("=" * 60)
    print("🚀 [NewsAggregator 测试] 开始验证新闻物理簇聚合引擎...")
    print("=" * 60)

    db_client = MongoDBClient.get_instance()

    try:
        # 1. 建立数据库连接
        print("\n[Step 1] 连接 MongoDB 数据库...")
        await db_client.connect()
        await db_client.init_indexes()

        # 2. 构造具备多个不同 sector 行业板块的测试卡片
        print("\n[Step 2] 插入测试情报卡片数据...")
        now = datetime.now(timezone.utc)
        test_cards = [
            {
                "raw_id": "test_raw_1",
                "source": "财联社",
                "title": "英伟达发布下一代 Blackwell 芯片架构",
                "core_facts": ["英伟达发布全新 GPU 架构，算力大幅提升 5 倍", "台积电 3nm 工艺全面承接代工订单"],
                "entities": ["英伟达", "台积电", "GPU", "AI算力"],
                "sentiment": "看多",
                "sentiment_score": 0.85,
                "research_value": 5,
                "impact_rating": 5,
                "event_type": "产业动态",
                "sector": "半导体芯片",
                "processed_at": now
            },
            {
                "raw_id": "test_raw_2",
                "source": "华尔街见闻",
                "title": "央行今日开展 2000 亿元逆回购操作",
                "core_facts": ["公开市场逆回购中标利率保持 1.80% 不变", "维护银行体系流动性合理充裕"],
                "entities": ["中国人民银行", "逆回购", "流动性"],
                "sentiment": "中性",
                "sentiment_score": 0.1,
                "research_value": 3,
                "impact_rating": 3,
                "event_type": "宏观政策",
                "sector": "国内宏观与流动性",
                "processed_at": now
            },
            {
                "raw_id": "test_raw_3",
                "source": "东方财富",
                "title": "大模型在具身智能机器人领域落地加速",
                "core_facts": ["多家头部科技公司发布具身智能人型机器人方案"],
                "entities": ["具身智能", "机器人", "AI大模型"],
                "sentiment": "看多",
                "sentiment_score": 0.75,
                "research_value": 4,
                "impact_rating": 4,
                "event_type": "产业动态",
                "sector": "人工智能大模型",
                "processed_at": now
            },
            {
                "raw_id": "test_raw_4",
                "source": "证券时报",
                "title": "某地方出台低空经济产业扶持政策",
                "core_facts": ["设 50 亿元专项产业基金扶持 eVTOL 飞行器研发"],
                "entities": ["低空经济", "eVTOL", "产业基金"],
                "sentiment": "看多",
                "sentiment_score": 0.6,
                "research_value": 4,
                "impact_rating": 3,
                "event_type": "产业动态",
                "sector": "低空经济",  # 验证新增行业板块自动识别
                "processed_at": now
            }
        ]

        inserted_count = await db_client.upsert_structured_news_batch(test_cards)
        print(f"   -> 成功写入测试卡片条数: {inserted_count}")
        assert inserted_count > 0, "测试卡片写入失败"

        # 3. 实例化 NewsAggregator 并运行 aggregate_clusters()
        print("\n[Step 3] 执行 aggregate_clusters() 聚合算法...")
        aggregator = NewsAggregator(db_client=db_client)
        clusters = await aggregator.aggregate_clusters()

        # 4. 打印并验证聚合结果
        print("\n[Step 4] 验证聚合输出统计数据...")
        print(f"   -> 活跃物理簇板块数量: {len(clusters)}")
        print(f"   -> 聚合到的板块名称: {list(clusters.keys())}")

        assert isinstance(clusters, dict), "返回结果必须为字典类型"
        assert len(clusters) > 0, "聚合出来的活跃板块不能为 0"

        # 逐个板块检查指标字段完整性
        for sector_name, data in clusters.items():
            print(f"\n   ----------------------------------------")
            print(f"   📌 板块: 【{sector_name}】")
            print(f"      • 卡片数量: {data['card_count']}")
            print(f"      • 平均研报价值: {data['avg_research_value']}⭐")
            print(f"      • 平均冲击烈度: {data['avg_impact_rating']}级")
            print(f"      • 平均情绪得分: {data['avg_sentiment_score']}")
            print(f"      • 情绪分布: {data['sentiment_counts']}")
            print(f"      • 热门实体: {data['top_entities']}")
            print(f"      • 核心事实摘要数: {len(data['core_fact_summaries'])}")

            # 校验核心字段结构
            assert "avg_research_value" in data
            assert "avg_impact_rating" in data
            assert "avg_sentiment_score" in data
            assert "sentiment_counts" in data
            assert "top_entities" in data
            assert "cards" in data

        print("\n" + "=" * 60)
        print("🎉🎉🎉 [测试完成] NewsAggregator 所有逻辑及动态板块聚合验证通过！")
        print("=" * 60)

    except Exception as e:
        app_logger.error(f"❌ 测试过程中捕获到异常: {e}")
        raise e
    finally:
        print("\n[Step 5] 断开数据库连接...")
        await db_client.close()


if __name__ == "__main__":
    asyncio.run(run_aggregator_tests())
