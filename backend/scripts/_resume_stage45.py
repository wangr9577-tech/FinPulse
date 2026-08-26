"""
临时断点续跑脚本：复用已落库的 structured_news_collection (2220 张卡片)，
跳过 node_extract，直接从 node_aggregate 起跑重跑 STAGE 4&5，产出日报 PDF。
运行完即刻删除，不入库。
"""
import asyncio
import sys
import os

# 将 backend 根目录加入 sys.path，确保 `from app...` 可导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.mongodb import MongoDBClient
from app.core.config import settings
from app.core.logger import app_logger
from app.core.pipeline_graph import (
    node_aggregate,
    node_analyze,
    node_synthesize,
    node_audit,
    node_validate_and_export,
)


async def resume():
    db = MongoDBClient.get_instance()
    await db.connect()

    # 沿用前端「研报中心」勾选的 report_sectors (默认 5 板块)；为空则回退全部分析
    try:
        cfg = await db.get_system_config()
        report_sectors = cfg.get("report_sectors", [])
    except Exception as e:
        app_logger.warning(f"[resume] 读取 report_sectors 失败，使用空配置: {e}")
        report_sectors = []

    state = {
        "hours_back": settings.REPORT_HOURS_BACK,
        "raw_news_list": [],
        "extracted_cards": [],
        "aggregated_clusters": {},
        "market_features": {},
        "sector_analysis_results": [],
        "synthesized_report": None,
        "audit_result": None,
        "validated_markdown": "",
        "pdf_output_path": "",
        "report_sectors": report_sectors,
    }
    print(f"[resume] 读取 report_sectors: {report_sectors}", flush=True)
    print("[resume] 开始 node_aggregate (读取结构化库 + 全量特征算子)...", flush=True)
    state = await node_aggregate(state)
    print(f"[resume] node_aggregate 完成: {len(state.get('aggregated_clusters', {}))} 个板块簇", flush=True)

    print("[resume] 开始 node_analyze (Analyst Agent 分板块推演)...", flush=True)
    state = await node_analyze(state)
    print(f"[resume] node_analyze 完成: {len(state.get('sector_analysis_results', []))} 个板块分析", flush=True)

    print("[resume] 开始 node_synthesize (Synthesizer Agent 全局统稿)...", flush=True)
    state = await node_synthesize(state)
    print("[resume] node_synthesize 完成", flush=True)

    print("[resume] 开始 node_audit (Auditor Agent 合规审查)...", flush=True)
    state = await node_audit(state)
    print("[resume] node_audit 完成", flush=True)

    print("[resume] 开始 node_validate_and_export (排版 + PDF 编译)...", flush=True)
    state = await node_validate_and_export(state)
    print(f"[resume] PDF 导出: {state.get('pdf_output_path')}", flush=True)
    print("RESUME_STAGE45_OK", flush=True)


if __name__ == "__main__":
    asyncio.run(resume())
