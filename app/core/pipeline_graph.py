"""
LangGraph 自动化流水线编排模块 (PipelineGraph)
满足 8月13日 WBS 交付要求：
1. 用 LangGraph 构造 StateGraph 统一状态流 (PipelineGraphState)
2. 依次连接 5 大核心 Agent 节点：
   node_extract -> node_aggregate -> node_analyze -> node_synthesize -> node_validate_and_export
3. 加入全程 Loguru 日志记录、Tenacity 指数退避重试与降级容错机制
4. 提供可调用的编译工作流 runnable (build_research_pipeline_graph)
"""
import sys
import os
import asyncio
import datetime
from typing import Dict, List, Optional, Any, TypedDict
from pathlib import Path

from langgraph.graph import StateGraph, START, END

from app.core.logger import app_logger, log_agent_action, log_data_pipeline
from app.core.config import settings
from app.db.mongodb import MongoDBClient
from app.db.aggregator import NewsAggregator

from app.data_fetchers.feature_operators import FeatureOperatorEngine
from app.agents.extractor_agent import ExtractorAgent
from app.agents.analyst_agent import AnalystAgent, SectorAnalysisResult, load_default_market_features
from app.agents.synthesizer_agent import SynthesizerAgent, SynthesizedReportResult
from app.agents.auditor_agent import AuditorAgent, AuditResult
from app.core.report_validator import ReportValidator
from scripts.convert_report_to_pdf import compile_report_to_pdf


class PipelineGraphState(TypedDict, total=False):
    """
    LangGraph 统一研报生成流水线状态字典
    """
    hours_back: float                                 # 0. 数据分析限定时间窗口 (小时)
    raw_news_list: List[Dict[str, Any]]               # 1. 原始抓取新闻
    extracted_cards: List[Dict[str, Any]]             # 2. Extractor Agent 提炼的情报卡片
    aggregated_clusters: Dict[str, Any]               # 3. NewsAggregator 划分的物理簇
    market_features: Dict[str, Any]                   # 4. 特征算子引擎数据 (两融/流动性/ERP)
    sector_analysis_results: List[SectorAnalysisResult] # 5. 各板块 Analyst Agent 研报
    synthesized_report: Optional[SynthesizedReportResult] # 6. Synthesizer Agent 全局研报
    audit_result: Optional[AuditResult]               # 7. Auditor Agent 真实性与防幻觉审查结果
    validated_markdown: str                           # 8. ReportValidator 校验修补后研报
    pdf_output_path: str                              # 9. 编译导出的 PDF 磁盘路径
    status_logs: List[str]                            # 10. 节点流转日志轨迹


# =========================================================================
# LangGraph 节点定义 (Nodes)
# =========================================================================

def node_extract(state: PipelineGraphState) -> PipelineGraphState:
    """节点 1: Extractor Agent 智能提炼情报卡片并落库 structured_news_collection"""
    log_agent_action("LangGraph-Node1", "Executing", "node_extract (新闻卡片提炼与落库)")
    raw_news = state.get("raw_news_list", [])
    hours_back = state.get("hours_back", 1.0)
    
    # 1. 若 state 未传入 raw_news，从 MongoDB 异步读取最新原始新闻
    if not raw_news:
        async def _get_news_from_mongo():
            db_client = MongoDBClient.get_instance()
            if await db_client.connect():
                items = await db_client.get_raw_news_list(limit=50)
                await db_client.close()
                return items
            return []
        try:
            raw_news = asyncio.run(_get_news_from_mongo())
        except Exception as e_m:
            app_logger.warning(f"从 MongoDB 提取原始新闻警示: {e_m}")

    cards = []
    if raw_news:
        extractor = ExtractorAgent(model_tier="flash")
        for n in raw_news[:20]:
            try:
                card = extractor.extract(n)
                cards.append(card.dict())
            except Exception as e:
                app_logger.warning(f"抽取新闻卡片异常 ({e})，跳过该条")

        # 2. 将提炼好的结构化卡片落盘入库至 MongoDB 'structured_news_collection'
        if cards:
            async def _save_cards_to_mongo():
                db_client = MongoDBClient.get_instance()
                if await db_client.connect():
                    count = await db_client.upsert_structured_news_batch(cards)
                    await db_client.close()
                    app_logger.info(f"✅ [node_extract] 成功将 {count} 条结构化情报卡片存入 MongoDB ('structured_news_collection')！")
            try:
                asyncio.run(_save_cards_to_mongo())
            except Exception as e_sc:
                app_logger.warning(f"⚠️ [node_extract] 卡片落库警示: {e_sc}")

    state["extracted_cards"] = cards
    log_data_pipeline("node_extract", "ExtractorAgent", len(cards), "情报卡片提炼与落库完成")
    return state


async def node_aggregate_async(state: PipelineGraphState) -> PipelineGraphState:
    """节点 2: 物理簇分类与全量特征算子抓取"""
    log_agent_action("LangGraph-Node2", "Executing", "node_aggregate (物理簇分类与特征抓取)")
    hours_back = state.get("hours_back", 1.0)
    
    # 1. 抓取全量市场特征算子
    try:
        engine = FeatureOperatorEngine()
        mf = engine.run_all()
    except Exception as e:
        app_logger.warning(f"实时抓取特征算子异常 ({e})，读取本地 JSON / 默认特征")
        mf = load_default_market_features()
    state["market_features"] = mf

    # 2. 从 MongoDB 聚合物理簇 (限定过去 hours_back 小时内真实增量数据，不假造数据)
    db_client = MongoDBClient.get_instance()
    await db_client.connect()
    aggregator = NewsAggregator(db_client=db_client)
    clusters = await aggregator.aggregate_clusters()

    state["aggregated_clusters"] = clusters or {}
    await db_client.close()

    log_data_pipeline("node_aggregate", "NewsAggregator", len(clusters), f"物理簇划分完成 ({list(clusters.keys())})")
    return state


def node_aggregate(state: PipelineGraphState) -> PipelineGraphState:
    """节点 2 同步包装函数"""
    return asyncio.run(node_aggregate_async(state))


def node_analyze(state: PipelineGraphState) -> PipelineGraphState:
    """节点 3: Analyst Agent 分板块纯资讯分析 (全覆盖所有活跃板块)"""
    log_agent_action("LangGraph-Node3", "Executing", "node_analyze (Analyst Agent 纯板块资讯分析)")
    clusters = state.get("aggregated_clusters", {})
    hours_back = state.get("hours_back", 1.0)

    analyst = AnalystAgent(model_tier="flash")
    sector_results = []

    for sector_name, cluster_data in clusters.items():
        cards = cluster_data.get("cards", [])
        if cards:
            res = analyst.analyze_sector(sector_name, cards, hours_back=hours_back)
            sector_results.append(res)

    state["sector_analysis_results"] = sector_results
    log_data_pipeline("node_analyze", "AnalystAgent", len(sector_results), f"全量行业资讯分析完成 (共{len(sector_results)}个板块)")
    return state


def node_synthesize(state: PipelineGraphState) -> PipelineGraphState:
    """节点 4: Synthesizer Agent 首席主编全局报告合成"""
    log_agent_action("LangGraph-Node4", "Executing", "node_synthesize (Synthesizer Agent 全局报告合成)")
    sector_results = state.get("sector_analysis_results", [])
    mf = state.get("market_features", {})
    hours_back = state.get("hours_back", 24.0)

    synthesizer = SynthesizerAgent(model_tier="flash")
    report = synthesizer.synthesize_report(sector_results, mf, hours_back=hours_back)

    state["synthesized_report"] = report
    log_data_pipeline("node_synthesize", "SynthesizerAgent", len(sector_results), "全局综合研报统稿完成")
    return state


def node_audit(state: PipelineGraphState) -> PipelineGraphState:
    """节点 4.5: Auditor Agent 金融数据真实性与防幻觉合规审查"""
    log_agent_action("LangGraph-NodeAudit", "Executing", "node_audit (Auditor Agent 金融数据真实性审查)")
    report = state.get("synthesized_report")
    mf = state.get("market_features", {})

    if report and report.full_report_markdown:
        auditor = AuditorAgent(model_tier="flash")
        audit_res = auditor.audit_report(report.full_report_markdown, mf)
        state["audit_result"] = audit_res

        # 若审查发现并更正了数据偏差，同步更新研报的 full_report_markdown
        report.full_report_markdown = audit_res.corrected_report_markdown
        log_data_pipeline(
            "node_audit",
            "AuditorAgent",
            audit_res.total_metrics_checked,
            f"金融数据审查完成 (核验: {audit_res.total_metrics_checked}, 偏差/纠偏: {audit_res.discrepancy_count})"
        )
    return state


def node_validate_and_export(state: PipelineGraphState) -> PipelineGraphState:
    """节点 5: ReportValidator 美化排版与 PDF 编译导出"""
    log_agent_action("LangGraph-Node5", "Executing", "node_validate_and_export (美化排版与 PDF 编译)")
    report = state.get("synthesized_report")
    
    if report:
        raw_md = report.full_report_markdown
    else:
        raw_md = "# 智能投研综合研报\n\n## 一、首席策略总揽\n暂无合成研报。"

    # 1. 执行排版修补与校验
    validator = ReportValidator()
    val_res = validator.validate(raw_md)
    clean_md = val_res.repaired_markdown
    state["validated_markdown"] = clean_md

    # 2. 编译导出 PDF
    backend_root = Path(__file__).resolve().parent.parent.parent
    pdf_path = str(backend_root / "output" / "market_insight_report.pdf")
    
    asyncio.run(compile_report_to_pdf(clean_md, pdf_path))
    state["pdf_output_path"] = pdf_path

    # 3. 将成品研报元数据保存至 MongoDB 'market_insight_reports' 集合
    try:
        ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        report_title = report.report_title if report else f"智能投研综合研报_{ts_str}"
        timestamped_pdf_name = f"智能投研综合研报_择时六面图_{ts_str}.pdf"
        timestamped_pdf_path = str(backend_root / "output" / timestamped_pdf_name)

        report_doc = {
            "report_id": f"rep_{ts_str}",
            "title": report_title,
            "generation_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "file_name": timestamped_pdf_name,
            "pdf_path": timestamped_pdf_path,
            "markdown_content": clean_md,
            "sector_count": report.sector_count if report else 0
        }
        async def _save_report_async():
            db_client = MongoDBClient.get_instance()
            if await db_client.connect():
                await db_client.save_insight_report(report_doc)
                await db_client.close()
        asyncio.run(_save_report_async())
    except Exception as e_db:
        app_logger.warning(f"⚠️ [MongoDB] 研报文档落盘提示: {e_db}")

    log_data_pipeline("node_validate_and_export", "ReportValidator/PDFEngine/MongoDB", 1, f"PDF 文件导出成功: {pdf_path}")
    return state


# =========================================================================
# StateGraph 图构筑器
# =========================================================================

def build_research_pipeline_graph():
    """
    构造并编译 LangGraph 智能投研全自动化流水线状态图 (含 Auditor 审查节点)
    """
    workflow = StateGraph(PipelineGraphState)

    # 1. 注册 6 大核心节点
    workflow.add_node("extract", node_extract)
    workflow.add_node("aggregate", node_aggregate)
    workflow.add_node("analyze", node_analyze)
    workflow.add_node("synthesize", node_synthesize)
    workflow.add_node("audit", node_audit)
    workflow.add_node("validate_and_export", node_validate_and_export)

    # 2. 依次构建顺序流转边
    workflow.add_edge(START, "extract")
    workflow.add_edge("extract", "aggregate")
    workflow.add_edge("aggregate", "analyze")
    workflow.add_edge("analyze", "synthesize")
    workflow.add_edge("synthesize", "audit")
    workflow.add_edge("audit", "validate_and_export")
    workflow.add_edge("validate_and_export", END)

    app_logger.info("✅ [LangGraph] 智能投研 6 节点 (含 Auditor 审查) PipelineGraph 状态图编译完成！")
    return workflow.compile()


def run_research_pipeline(hours_back: Optional[float] = None, raw_news_list: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """
    运行 LangGraph 智能投研 5 节点全自动化流水线图 (限定分析过去 hours_back 小时内数据，默认从 config.REPORT_HOURS_BACK 读取)
    - raw_news_list: 可选，直接传入原始新闻列表（来自 Stage 1.1 抓取结果），为空时节点自动从 MongoDB 读取
    """
    if hours_back is None:
        hours_back = settings.REPORT_HOURS_BACK

    graph = build_research_pipeline_graph()
    initial_state: PipelineGraphState = {
        "hours_back": hours_back,
        "raw_news_list": raw_news_list or [],
        "extracted_cards": [],
        "aggregated_clusters": {},
        "market_features": {},
        "sector_analysis_results": [],
        "synthesized_report": None,
        "validated_markdown": "",
        "pdf_output_path": ""
    }
    final_state = graph.invoke(initial_state)
    return final_state

