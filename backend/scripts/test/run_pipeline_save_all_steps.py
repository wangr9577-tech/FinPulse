# -*- coding: utf-8 -*-
"""
智能投研全流程分步导出测试脚本 (run_pipeline_save_all_steps.py)
========================================================================
运行完整端到端投研流水线，并将【每一个步骤】的中间与最终计算结果
格式化导出落盘为 CSV 表格、HTML 视图以及 Playwright 高保真 PDF 研报。

导出目录：
- backend/output/pipeline_steps/
  - 01_raw_news.csv               (Stage 1: 舆情全量原始新闻)
  - 02_timing_hexagon_signals.csv (Stage 2: 择时六面图 34 项量化指标与信号)
  - 02_feature_operators.csv       (Stage 2: 特征算子 4 大类别宏观杠杆指标)
  - 03_structured_cards.csv       (Stage 3: Extractor 提炼的结构化情报卡片)
  - 04_sector_analysis.csv        (Stage 4: Analyst 分板块纯资讯总结与情绪)
  - 05_financial_audit_results.csv(Stage 5: Auditor 金融数据真实性核验明细)
  - 06_report_summary.csv         (Stage 6: Synthesizer 研报元数据与风控警示)
  - 06_market_insight_report.pdf  (Stage 6: 高保真金融研报 PDF)
  - 06_market_insight_report.html (Stage 6: 美化排版 HTML 视图)

用法：
    python backend/scripts/run_pipeline_save_all_steps.py [--hours 24.0]
"""
import sys
import os
import time
import csv
import json
import asyncio
import datetime
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

# 保证控制台 UTF-8 输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.config import settings, PROJECT_ROOT as BASE_DIR
from app.core.logger import app_logger, log_data_pipeline
from app.data_fetchers.flash_news_fetcher import FlashNewsFetcher
from app.timing_hexagon.pipeline import run_timing_hexagon_pipeline
from app.data_fetchers.feature_operators import FeatureOperatorEngine
from app.core.pipeline_graph import run_research_pipeline
from app.db.mongodb import MongoDBClient


def ensure_output_dirs() -> Path:
    """创建并返回分步输出文件夹"""
    output_dir = settings.OUTPUT_DIR / "pipeline_steps"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def export_stage1_raw_news_to_csv(raw_news: List[Dict[str, Any]], export_path: Path):
    """保存 Stage 1 抓取的原始新闻为 CSV"""
    fieldnames = ["news_id", "title", "source", "publish_time", "sector", "category_tags", "content"]
    with open(export_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for item in raw_news:
            tags = item.get("category_tags", [])
            if isinstance(tags, list):
                tags_str = "|".join(str(t) for t in tags)
            else:
                tags_str = str(tags)
            writer.writerow({
                "news_id": item.get("news_id", ""),
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "publish_time": item.get("publish_time", ""),
                "sector": item.get("sector", "其他板块"),
                "category_tags": tags_str,
                "content": item.get("content", "").replace("\n", " ")[:300]
            })
    app_logger.info(f"💾 [CSV 导出] 成功保存 Stage 1 原始新闻 ({len(raw_news)} 条) -> {export_path}")


def export_stage2_timing_to_csv(market_features: Dict[str, Any], output_dir: Path):
    """保存 Stage 2 择时六面图指标与特征算子为 CSV"""
    # 1. 择时 34 项指标与信号 CSV
    timing_path = output_dir / "02_timing_hexagon_signals.csv"
    indicators = market_features.get("timing_hexagon", {}).get("indicators", [])
    
    with open(timing_path, "w", newline="", encoding="utf-8-sig") as f:
        fieldnames = ["dimension", "indicator", "signal_score", "signal_text", "value"]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for ind in indicators:
            writer.writerow({
                "dimension": ind.get("dimension", ""),
                "indicator": ind.get("indicator", ""),
                "signal_score": ind.get("signal_score", 0.0),
                "signal_text": ind.get("signal_text", "中性"),
                "value": ind.get("value", 0.0)
            })
    app_logger.info(f"💾 [CSV 导出] 成功保存 Stage 2 择时六面图信号 ({len(indicators)} 项) -> {timing_path}")

    # 2. 特征算子 4 大类汇总 CSV
    op_path = output_dir / "02_feature_operators.csv"
    operators = market_features.get("operators", {})
    with open(op_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["operator_category", "metric_key", "metric_value"])
        for cat, metrics in operators.items():
            if isinstance(metrics, dict):
                for k, v in metrics.items():
                    writer.writerow([cat, k, str(v)])
    app_logger.info(f"💾 [CSV 导出] 成功保存 Stage 2 特征算子数值 -> {op_path}")


def export_stage3_cards_to_csv(cards: List[Dict[str, Any]], export_path: Path):
    """保存 Stage 3 Extractor Agent 提炼的情报卡片为 CSV"""
    fieldnames = ["news_id", "title", "sector", "sentiment", "impact_rating", "event_type", "summary", "key_metrics"]
    with open(export_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for c in cards:
            metrics = c.get("key_metrics", {})
            metrics_str = json.dumps(metrics, ensure_ascii=False) if isinstance(metrics, dict) else str(metrics)
            writer.writerow({
                "news_id": c.get("news_id", ""),
                "title": c.get("title", ""),
                "sector": c.get("sector", ""),
                "sentiment": c.get("sentiment", ""),
                "impact_rating": c.get("impact_rating", 0),
                "event_type": c.get("event_type", ""),
                "summary": c.get("summary", ""),
                "key_metrics": metrics_str
            })
    app_logger.info(f"💾 [CSV 导出] 成功保存 Stage 3 结构化情报卡片 ({len(cards)} 条) -> {export_path}")


def export_stage4_sectors_to_csv(sector_results: List[Any], export_path: Path):
    """保存 Stage 4 Analyst Agent 板块分析结果为 CSV"""
    fieldnames = ["sector_name", "card_count", "sentiment_bias", "summary", "key_drivers", "catalyst_events"]
    with open(export_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for res in sector_results:
            bias = res.sentiment_bias.value if hasattr(res.sentiment_bias, "value") else str(res.sentiment_bias)
            drivers = "|".join(res.key_drivers) if hasattr(res, "key_drivers") and isinstance(res.key_drivers, list) else ""
            events = "|".join(res.catalyst_events) if hasattr(res, "catalyst_events") and isinstance(res.catalyst_events, list) else ""
            writer.writerow({
                "sector_name": getattr(res, "sector_name", ""),
                "card_count": getattr(res, "card_count", 0),
                "sentiment_bias": bias,
                "summary": getattr(res, "summary", ""),
                "key_drivers": drivers,
                "catalyst_events": events
            })
    app_logger.info(f"💾 [CSV 导出] 成功保存 Stage 4 板块分析总结 ({len(sector_results)} 个板块) -> {export_path}")


def export_stage5_audit_to_csv(audit_result: Any, export_path: Path):
    """保存 Stage 5 Auditor Agent 金融真实性审查为 CSV"""
    fieldnames = ["metric_name", "cited_value", "ground_truth_value", "is_matched", "comment"]
    items = []
    if hasattr(audit_result, "verified_metrics") and audit_result.verified_metrics:
        items.extend(audit_result.verified_metrics)
    if hasattr(audit_result, "discrepancies") and audit_result.discrepancies:
        items.extend(audit_result.discrepancies)

    with open(export_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            writer.writerow({
                "metric_name": getattr(item, "metric_name", ""),
                "cited_value": getattr(item, "cited_value", ""),
                "ground_truth_value": getattr(item, "ground_truth_value", ""),
                "is_matched": getattr(item, "is_matched", True),
                "comment": getattr(item, "comment", "")
            })
    app_logger.info(f"💾 [CSV 导出] 成功保存 Stage 5 金融合规核验 ({len(items)} 项) -> {export_path}")


def export_stage6_report_summary_to_csv(report: Any, export_path: Path):
    """保存 Stage 6 Synthesizer 研报元数据与风控警示为 CSV"""
    fieldnames = ["report_title", "generation_date", "sector_count", "key_macro_alerts", "cross_sector_chains"]
    with open(export_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        if report:
            alerts = "|".join(getattr(report, "key_macro_alerts", []))
            chains = "|".join(getattr(report, "cross_sector_chains", []))
            writer.writerow({
                "report_title": getattr(report, "report_title", ""),
                "generation_date": getattr(report, "generation_date", ""),
                "sector_count": getattr(report, "sector_count", 0),
                "key_macro_alerts": alerts,
                "cross_sector_chains": chains
            })
    app_logger.info(f"💾 [CSV 导出] 成功保存 Stage 6 研报摘要 -> {export_path}")


def run_pipeline_and_export_all(hours_back: Optional[float] = None):
    """全流程运行并分步导出 CSV/PDF/HTML"""
    if hours_back is None:
        hours_back = settings.REPORT_HOURS_BACK

    output_steps_dir = ensure_output_dirs()
    start_time = time.time()

    print("=" * 80)
    print(" 🚀 智能投研信息引擎 - 全流程分步导出运行脚本 (Run Pipeline & Save All Steps)")
    print("=" * 80)
    print(f" 启动时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f" 分析时间窗口: 过去 {hours_back:.1f} 小时")
    print(f" 导出文件目录: {output_steps_dir}")
    print("=" * 80 + "\n")

    # -------------------------------------------------------------------------
    # STAGE 1: 资讯抓取
    # -------------------------------------------------------------------------
    print(f"📌 [STAGE 1] 抓取 28 大媒体高频新闻快讯 (过去 {hours_back}h)...")
    async def _fetch_news():
        fetcher = FlashNewsFetcher()
        items = await fetcher.fetch_all_flash_news()
        raw_dicts = [item.model_dump() for item in items]
        if raw_dicts:
            client = MongoDBClient()
            if await client.connect():
                await client.upsert_raw_news_batch(raw_dicts)
                await client.close()
        return raw_dicts

    raw_news = asyncio.run(_fetch_news())
    export_stage1_raw_news_to_csv(raw_news, output_steps_dir / "01_raw_news.csv")

    # 择时爬虫
    try:
        backend_dir = settings.BASE_DIR
        subprocess.run([sys.executable, "-m", "app.data_fetchers.crawler.run_all"], cwd=backend_dir, capture_output=True, text=True)
    except Exception as e:
        app_logger.warning(f"爬虫调度提示: {e}")

    # -------------------------------------------------------------------------
    # STAGE 2: 择时六面图与特征算子
    # -------------------------------------------------------------------------
    print("📌 [STAGE 2] 择时六面图 34 项指标与 4 大特征算子计算...")
    run_timing_hexagon_pipeline()
    engine = FeatureOperatorEngine()
    market_features = engine.run_all()
    export_stage2_timing_to_csv(market_features, output_steps_dir)

    # -------------------------------------------------------------------------
    # STAGE 3, 4, 5, 6: LangGraph AI 流水线 (卡片 -> 板块 -> 统稿 -> 审查 -> PDF)
    # -------------------------------------------------------------------------
    print("📌 [STAGE 3~6] 启动 AI 流水线并进行分步结果捕获...")
    final_state = run_research_pipeline(hours_back=hours_back, raw_news_list=raw_news)

    # 分步导出卡片、板块分析与审查结果
    cards = final_state.get("extracted_cards", [])
    export_stage3_cards_to_csv(cards, output_steps_dir / "03_structured_cards.csv")

    sector_results = final_state.get("sector_analysis_results", [])
    export_stage4_sectors_to_csv(sector_results, output_steps_dir / "04_sector_analysis.csv")

    audit_res = final_state.get("audit_result")
    export_stage5_audit_to_csv(audit_res, output_steps_dir / "05_financial_audit_results.csv")

    report = final_state.get("synthesized_report")
    export_stage6_report_summary_to_csv(report, output_steps_dir / "06_report_summary.csv")

    # 复制最终 PDF/HTML 至 pipeline_steps 目录
    main_output_dir = settings.OUTPUT_DIR
    pdf_source = main_output_dir / "market_insight_report.pdf"
    html_source = main_output_dir / "market_insight_report.html"

    pdf_dest = output_steps_dir / "06_market_insight_report.pdf"
    html_dest = output_steps_dir / "06_market_insight_report.html"

    if pdf_source.exists():
        import shutil
        shutil.copy(pdf_source, pdf_dest)
    if html_source.exists():
        import shutil
        shutil.copy(html_source, html_dest)

    total_time = time.time() - start_time
    print("\n" + "=" * 80)
    print(" 🎉 [运行与导出全部成功] 智能投研全流程分步导出完成！")
    print("=" * 80)
    print(f" ⏱️ 累计总耗时: {total_time:.2f} 秒")
    print(f"\n 📂 分步 CSV/PDF 导出文件列表 (位于: {output_steps_dir}):")
    print(f"   1. [Stage 1 原始新闻 CSV]: {output_steps_dir / '01_raw_news.csv'}")
    print(f"   2. [Stage 2 择时指标 CSV]: {output_steps_dir / '02_timing_hexagon_signals.csv'}")
    print(f"   3. [Stage 2 特征算子 CSV]: {output_steps_dir / '02_feature_operators.csv'}")
    print(f"   4. [Stage 3 情报卡片 CSV]: {output_steps_dir / '03_structured_cards.csv'}")
    print(f"   5. [Stage 4 板块总结 CSV]: {output_steps_dir / '04_sector_analysis.csv'}")
    print(f"   6. [Stage 5 合规审查 CSV]: {output_steps_dir / '05_financial_audit_results.csv'}")
    print(f"   7. [Stage 6 研报摘要 CSV]: {output_steps_dir / '06_report_summary.csv'}")
    print(f"   8. [Stage 6 研报 HTML 视图]: {html_dest}")
    print(f"   9. [Stage 6 高保真 PDF 研报]: {pdf_dest}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="智能投研全流程分步导出运行脚本")
    parser.add_argument("--hours", type=float, default=1.0, help="分析时间窗口 (默认 1.0 小时速跑测试)")
    args = parser.parse_args()
    run_pipeline_and_export_all(hours_back=args.hours)
