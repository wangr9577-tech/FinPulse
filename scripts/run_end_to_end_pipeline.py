# -*- coding: utf-8 -*-
"""
智能投研全自动化一键运行主入口 (run_end_to_end_pipeline.py)
========================================================================
从零跑通全流程闭环：
1. 【数据爬取】全量 28 大媒体高频快讯 + 择时六面图 35 项指标多源抓取；
2. 【择时计算】数据标准化清洗 (01) -> 35 项无未来函数指标计算 (02) -> 03 质量检查断言；
3. 【算子与落盘】FeatureOperatorEngine 算子计算 + MongoDB 数据库全量导入；
4. 【AI 深度推演】Analyst Agent 融合真实资金证据进行行业推演；
5. 【全局研报合成】Synthesizer Agent 仿国盛证券择时六面图 6 维分析与 35 项表格统稿；
6. 【PDF 编译导出】ReportValidator 美化排版 + Playwright PDF 引擎编译导出。

用法：
    python backend/scripts/run_end_to_end_pipeline.py
"""
import sys
import os
import time
import datetime
import subprocess
from typing import Optional, List, Dict, Any
from pathlib import Path


# 确保 UTF-8 控制台输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.logger import app_logger, log_data_pipeline, log_agent_action

from app.data_fetchers.flash_news_fetcher import FlashNewsFetcher
from app.timing_hexagon.pipeline import run_timing_hexagon_pipeline
from app.core.config import settings, PROJECT_ROOT as BASE_DIR
from app.data_fetchers.feature_operators import FeatureOperatorEngine
from app.core.pipeline_graph import run_research_pipeline



def run_end_to_end_pipeline(hours_back: Optional[float] = None):
    if hours_back is None:
        hours_back = settings.REPORT_HOURS_BACK

    start_total_time = time.time()
    print("=" * 80)
    print(" 🚀 智能投研信息引擎 - 全自动化一键运行主入口 (End-to-End Master Pipeline)")
    print("=" * 80)
    print(f" 启动时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f" 分析时间窗口: 过去 {hours_back:.1f} 小时 (根据 config.REPORT_HOURS_BACK 设定)")

    print(" 闭环流程: [数据爬取] -> [择时计算] -> [数据库落盘] -> [AI智能体推演] -> [PDF研报导出]")
    print("=" * 80 + "\n")

    # -------------------------------------------------------------------------
    # STAGE 1: 资讯与 35 项指标多源数据抓取
    # -------------------------------------------------------------------------
    print(f"📌 [STAGE 1/5] 启动数据爬取引擎 (28大媒体快讯 + 择时35项指标, 时间窗口: 过去 {hours_back} 小时)...")
    s1_start = time.time()
    
    # 1.1 全量 28 大媒体高频快讯拉取与 MongoDB 舆情数据库落盘
    raw_news_dicts = []  # 用于传递给 Stage 4 AI 流水线的原始新闻 dict 列表
    try:
        import asyncio
        from app.db.mongodb import MongoDBClient

        async def _fetch_and_store_news():
            app_logger.info(f"[STAGE 1.1] 正在抓取全量 28 大媒体高频新闻快讯 (过去 {hours_back}h)...")
            news_fetcher = FlashNewsFetcher()
            fetched_news = await news_fetcher.fetch_all_flash_news()
            app_logger.info(f"✅ [STAGE 1.1] 抓取完成！共获取 {len(fetched_news)} 条 {hours_back}h 内增量资讯。")

            dicts = []
            if fetched_news:
                dicts = [item.model_dump() for item in fetched_news]
                db_client = MongoDBClient()
                connected = await db_client.connect()
                if connected:
                    inserted_count = await db_client.upsert_raw_news_batch(dicts)
                    await db_client.close()
                    app_logger.info(f"✅ [STAGE 1.1] 成功将 {inserted_count} 条舆情新闻数据存入 MongoDB ('raw_news_collection') 数据库！")
            return dicts

        raw_news_dicts = asyncio.run(_fetch_and_store_news())
    except Exception as e_news:
        app_logger.error(f"❌ [STAGE 1.1] 新闻快讯抓取或 MongoDB 入库失败: {e_news}")
        raise RuntimeError(f"[STAGE 1.1 异常中断] 新闻抓取或入库失败: {e_news}") from e_news

    # 1.2 择时六面图 35 项核心指标爬虫调度
    try:
        app_logger.info("[STAGE 1.2] 正在调度择时 35 项指标多源爬虫 (AKShare + 官方 API)...")
        backend_dir = Path(__file__).resolve().parent.parent
        proc = subprocess.run(
            [sys.executable, "-m", "app.data_fetchers.crawler.run_all"],
            cwd=backend_dir,
            capture_output=True,
            text=True
        )

        if proc.returncode == 0:
            app_logger.info("✅ [STAGE 1.2] 择时 35 项指标数据更新成功！")
        else:
            app_logger.error(f"❌ [STAGE 1.2] 爬虫运行失败 (退出码: {proc.returncode}): {proc.stderr or proc.stdout}")
            raise RuntimeError(f"[STAGE 1.2 异常中断] 爬虫运行失败，退出码: {proc.returncode}")
    except Exception as e_crawl:
        app_logger.error(f"❌ [STAGE 1.2] 爬虫调度异常: {e_crawl}")
        raise RuntimeError(f"[STAGE 1.2 异常中断] 爬虫调度异常: {e_crawl}") from e_crawl

    s1_elapsed = time.time() - s1_start
    print(f"   └─ STAGE 1 完成，耗时: {s1_elapsed:.2f} 秒\n")

    # -------------------------------------------------------------------------
    # STAGE 2: 择时六面图数据清洗、指标计算与合规检查
    # -------------------------------------------------------------------------
    print("📌 [STAGE 2/5] 启动择时六面图无未来函数清洗与计算引擎...")
    s2_start = time.time()
    
    try:
        success = run_timing_hexagon_pipeline()
        if success:
            app_logger.info("✅ [STAGE 2] 择时六面图 01清洗 -> 02计算 -> 03质量检查 全部成功！")
        else:
            app_logger.error("❌ [STAGE 2] 择时流水线未完全成功，中断流程。")
            raise RuntimeError("[STAGE 2 异常中断] 择时六面图清洗计算质量检查未完全通过")
    except Exception as e_timing:
        app_logger.error(f"❌ [STAGE 2] 择时六面图计算异常: {e_timing}")
        raise RuntimeError(f"[STAGE 2 异常中断] 择时六面图计算异常: {e_timing}") from e_timing

    s2_elapsed = time.time() - s2_start
    print(f"   └─ STAGE 2 完成，耗时: {s2_elapsed:.2f} 秒\n")

    # -------------------------------------------------------------------------
    # STAGE 3: 特征算子计算与 MongoDB 数据库入库
    # -------------------------------------------------------------------------
    print("📌 [STAGE 3/5] 执行特征算子整合与 MongoDB 数据库全量落盘...")
    s3_start = time.time()

    # 3.1 运行特征算子引擎
    try:
        engine = FeatureOperatorEngine()
        feat_report = engine.run_all()
        app_logger.info("✅ [STAGE 3.1] FeatureOperatorEngine 算子计算与 JSON 导出成功！")
    except Exception as e_feat:
        app_logger.error(f"❌ [STAGE 3.1] 特征算子计算异常: {e_feat}")
        raise RuntimeError(f"[STAGE 3.1 异常中断] 特征算子计算失败: {e_feat}") from e_feat

    # 3.2 运行数据库入库脚本
    try:
        db_script = BASE_DIR / "backend" / "scripts" / "import_source_data_to_db.py"
        proc_db = subprocess.run(
            [sys.executable, str(db_script)],
            cwd=BASE_DIR,
            capture_output=True,
            text=True
        )
        if proc_db.returncode == 0:
            app_logger.info("✅ [STAGE 3.2] source_data 与最新信号数据成功存入 MongoDB！")
        else:
            app_logger.error(f"❌ [STAGE 3.2] MongoDB 数据导入失败: {proc_db.stderr or proc_db.stdout}")
            raise RuntimeError(f"[STAGE 3.2 异常中断] 数据库导入失败 (退出码: {proc_db.returncode})")
    except Exception as e_db:
        app_logger.error(f"❌ [STAGE 3.2] 数据库导入脚本异常: {e_db}")
        raise RuntimeError(f"[STAGE 3.2 异常中断] 数据库导入脚本异常: {e_db}") from e_db

    s3_elapsed = time.time() - s3_start
    print(f"   └─ STAGE 3 完成，耗时: {s3_elapsed:.2f} 秒\n")

    # -------------------------------------------------------------------------
    # STAGE 4 & 5: AI 智能体推演、国盛证券择时六面图统稿与 PDF 编译导出
    # -------------------------------------------------------------------------
    print("📌 [STAGE 4 & 5/5] 启动 LangGraph 5 节点 AI 流水线 (推演 -> 国盛择时六面图统稿 -> PDF 编译)...")
    s4_start = time.time()

    try:
        app_logger.info(f"[STAGE 4] 将 {len(raw_news_dicts)} 条原始新闻直接传入 AI 流水线进行情报卡片提炼...")
        final_state = run_research_pipeline(hours_back=hours_back, raw_news_list=raw_news_dicts)
        
        pdf_path = BASE_DIR / "backend" / "output" / "market_insight_report.pdf"
        html_path = BASE_DIR / "backend" / "output" / "market_insight_report.html"
        json_path = BASE_DIR / "backend" / "output" / "feature_operators_output.json"

        s4_elapsed = time.time() - s4_start
        total_elapsed = time.time() - start_total_time

        print("\n" + "=" * 80)
        print(" 🎉 [全流程跑通成功] 智能投研全自动化流水线运行完成！")
        print("=" * 80)
        print(f" ⏱️ 累计总耗时: {total_elapsed:.2f} 秒 (数据抓取: {s1_elapsed:.1f}s | 择时计算: {s2_elapsed:.1f}s | 入库: {s3_elapsed:.1f}s | AI/PDF: {s4_elapsed:.1f}s)")
        print("\n 📁 核心产出文件路径汇总:")
        print(f"   1. [高保真金融 PDF 研报]: {pdf_path}")
        print(f"   2. [美化 HTML 视图文件]: {html_path}")
        print(f"   3. [特征算子与择时 JSON]: {json_path}")
        print(f"   4. [MongoDB 数据库集合]: intelligent_research_db (timing_source_data & timing_signals_summary)")
        print("=" * 80 + "\n")

    except Exception as e_pipeline:
        app_logger.error(f"❌ [STAGE 4&5] AI 流水线或 PDF 编译失败: {e_pipeline}")
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="智能投研全自动化流水线")
    parser.add_argument("--hours", "--hours-back", type=float, default=None, help=f"分析时间窗口 (过去多少小时的数据, 默认由 config.REPORT_HOURS_BACK 配置: {settings.REPORT_HOURS_BACK}h)")
    args = parser.parse_args()
    run_end_to_end_pipeline(hours_back=args.hours)

