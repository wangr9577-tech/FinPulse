"""
第三层 Synthesizer Agent (首席策略分析师 / 投研主编智能体)
========================================================================
架构原则：模块化直拼架构 (Direct Assembly Architecture)
1. ## 一、总评：由 Synthesizer Agent (CIO) 专精撰写全局策略总揽、风险警示、跨行业传导链与仓位建议。
2. ## 二、择时六面图：由代码强控制固定输出（6 大维度，各 3~4 个指标，1 指标 1 行），配合 LLM 返回各面总结论。
3. ## 三、资讯分析：直接以 Python 代码无损拼接各板块 Analyst Agent 总结，100% 完整保留。
"""
import json
import re
import datetime
import pandas as pd
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from app.core.logger import app_logger, log_agent_action
from app.core.config import settings
from app.core.llm_factory import LLMFactory
from app.core.skill_loader import SkillLoader
from app.agents.analyst_agent import SectorAnalysisResult


class SynthesizedReportResult(BaseModel):
    """
    Synthesizer Agent 首席策略分析师全局综合报告结果模型
    """
    report_title: str = Field(..., description="综合投研报告标题")
    generation_date: str = Field(..., description="报告生成日期 (YYYY-MM-DD)")
    sector_count: int = Field(0, description="参与合成的行业/物理簇数量")
    macro_executive_summary: str = Field(..., description="首席策略分析师全局总揽综述 (Markdown)")
    key_macro_alerts: List[str] = Field(default_factory=list, description="核心宏观与市场风险警示列表")
    cross_sector_chains: List[str] = Field(default_factory=list, description="跨行业连锁反应与逻辑溢出链条列表")
    resolved_conflicts: List[str] = Field(default_factory=list, description="冲突消除与辩证归因说明列表")
    full_report_markdown: str = Field(..., description="排版完整的全篇 Markdown 综合投研报告")


SYNTHESIZER_SYSTEM_PROMPT = """你是一位资深的买方公募/私募头部基金【首席策略分析师 / CIO】。
你的任务是根据给定的【择时六面图 (量化金融数据)】与【资讯分析 (下属各行业分析师提交的纯新闻总结)】，撰写第一章【## 一、总评】。

【第一章 ## 一、总评 撰写要求】：
必须且只能包含以下 5 个核心部分：
1. **【首席策略总揽】**：结合择时六面图信号与全行业舆情，给出全市场多空研判与核心观点。
2. **【核心宏观与市场风险警示】**：列出 2-3 条当前市场最关键的宏观/资金/风险警示。
3. **【跨行业传导与逻辑溢出链条】**：推演产业链与行业资金传导（如：`【上游半导体 -> 中游AI服务器 -> 下游大模型应用】`）。
4. **【冲突消解与辩证归因】**：若量化择时信号与行业新闻情绪存在分歧（例如流动性紧缩但科技板块看多），给出买方归因解释。
5. **【大类资产配置与仓位建议】**：给出明确的仓位管理与配置策略。

【输出格式要求】：
必须且只能输出严格的 JSON 格式对象，结构如下：
{
  "report_title": "YYYY年MM月DD日 智能投研全市场综合研报：择时六面图 流动性偏多、景气度中性",
  "macro_executive_summary": "#### 【首席策略总揽】\\n...",
  "key_macro_alerts": ["核心风险警示 1", "核心风险警示 2"],
  "cross_sector_chains": ["【半导体 -> AI算力】上游 Chiplet 通线降低 AI 算力芯片封测成本"],
  "resolved_conflicts": ["消解【科技看多】与【流动性偏紧】冲突..."],
  "asset_allocation_advice": "建议保持 6-7 成中性偏高仓位..."
}
"""


def _generate_dimension_summaries(dim_indicators_map: Dict[str, List[str]], llm_factory: LLMFactory) -> Dict[str, str]:
    """
    调用 LLM 为择时六面图 6 大维度分别生成 1 句总结论
    """
    formatted_prompt_parts = []
    for dim_name, lines in dim_indicators_map.items():
        ind_text = "\n".join(lines) if lines else "暂无指标数据"
        formatted_prompt_parts.append(f"【{dim_name}维度指标】:\n{ind_text}")

    prompt_body = "\n\n".join(formatted_prompt_parts)
    prompt = (
        "你是资深买方量化策略分析师。请根据以下择时六面图各维度的 3-4 项量化指标，"
        "为 6 个维度各生成一段 1 句精炼的【总结论】（必须包含明确的方向如 看多 / 看空 / 中性 及归因说明，严禁使用任何Emoji符号）。\n\n"
        f"{prompt_body}\n\n"
        "【输出格式】：必须输出 JSON 字典，键为维度名称，值为总结论字符串。例如：\n"
        "{\n"
        '  "流动性维度": "看多；短端资金利率维持低位，货币与信用传导顺畅，流动性整体充裕。",\n'
        '  "宏观经济维度": "中性；制造业 PMI 在荣枯线附近震荡，通胀指标保持低位筑底。",\n'
        '  "估值维度": "看多；股权风险溢价 (ERP) 处于历史极具性价比区间，绝对估值具备安全边际。",\n'
        '  "资金面维度": "中性；两融杠杆资金交易占比平稳，新增开户数维持中性震荡。",\n'
        '  "技术面维度": "看多；均线系统维持多头排列，量价时钟归属于低风险象限。",\n'
        '  "情绪与期权面维度": "中性；全市场炸板率与期权 QVIX 波动率维持在安全边界内。"\n'
        "}"
    )

    try:
        llm = llm_factory.get_llm()
        response_text = llm_factory.invoke_with_circuit_breaker(llm, prompt)
        clean_text = response_text.strip()
        if "```json" in clean_text:
            clean_text = clean_text.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```")[1].split("```")[0].strip()
        
        summaries = json.loads(clean_text)
        return summaries
    except Exception as e:
        app_logger.error(f"[SynthesizerAgent] LLM 生成六面图总结论失败: {e}")
        raise RuntimeError(f"[SynthesizerAgent] LLM 生成六面图总结论失败: {e}") from e


def build_timing_hexagon_markdown_chapter(
    timing_data: Dict[str, Any],
    hours_back: float = 24.0,
    llm_factory: Optional[LLMFactory] = None,
    chart_paths_map: Optional[Dict[str, str]] = None
) -> str:
    """
    构建符合《择时六面图》标准的第二章节 Markdown (带指标高保真折线图与雷达图)
    """
    if chart_paths_map is None:
        try:
            from app.timing_hexagon.plotter import generate_all_hexagon_charts
            chart_paths_map = generate_all_hexagon_charts()
        except Exception as e:
            app_logger.error(f"研报图表生成引擎运行失败: {e}")
            raise RuntimeError(f"[SynthesizerAgent] 研报图表生成引擎运行失败: {e}") from e

    timing = timing_data.get("timing_hexagon", {})
    ops = timing_data.get("operators", {})

    lev = ops.get("leverage_capital", {})
    macro = ops.get("macro_liquidity", {})
    val = ops.get("valuation_and_breadth", {})

    indicators = timing.get("indicators", [])

    def _format_val(ind_name: str, raw_val: Any) -> str:
        if raw_val is not None and not pd.isna(raw_val) and str(raw_val).strip() != "":
            try:
                v = float(raw_val)
                if abs(v) >= 1e12:
                    return f"{v / 1e12:.2f}万亿元"
                elif abs(v) >= 1e8:
                    return f"{v / 1e8:.2f}亿元"
                elif any(k in ind_name for k in ["同比", "率", "利差", "剪刀差", "占比", "溢价", "RSI", "偏离度", "新高", "新低"]):
                    return f"{v:.2f}%" if not str(raw_val).endswith("%") else f"{v:.2f}"
                elif abs(v) < 100:
                    return f"{v:.2f}"
                else:
                    return f"{v:,.2f}"
            except Exception:
                return str(raw_val)
        return "暂无数据"

    # 按维度整理指标
    dim_raw = {
        "流动性维度": [],
        "宏观经济维度": [],
        "估值维度": [],
        "资金面维度": [],
        "技术面维度": [],
        "情绪与期权面维度": []
    }

    for item in indicators:
        dim = item.get("dimension", "")
        ind = item.get("indicator", "")
        score = item.get("signal_score")
        raw_v = item.get("latest_value")

        if score == 1.0:
            signal_str = "看多"
        elif score == -1.0:
            signal_str = "看空"
        else:
            signal_str = "中性"

        txt = item.get("signal_text", "中性")
        val_str = _format_val(ind, raw_v)
        line = f"- **{ind}** | **指标值**：{val_str} | **结论**：{signal_str} ({txt})"

        # 匹配对应图表
        chart_url = chart_paths_map.get(ind) or chart_paths_map.get(f"{dim}_{ind}")
        if not chart_url:
            for k, v in chart_paths_map.items():
                if ind in k:
                    chart_url = v
                    break
        if chart_url:
            line += f"\n  ![{ind} 走势图]({chart_url})"

        if "流动性" in dim:
            dim_raw["流动性维度"].append(line)
        elif "经济" in dim:
            dim_raw["宏观经济维度"].append(line)
        elif "估值" in dim:
            dim_raw["估值维度"].append(line)
        elif "资金" in dim:
            dim_raw["资金面维度"].append(line)
        elif "技术" in dim:
            dim_raw["技术面维度"].append(line)
        elif "情绪" in dim or "期权" in dim:
            dim_raw["情绪与期权面维度"].append(line)

    # 整理各维度指标列表
    final_dim_map = {k: v for k, v in dim_raw.items()}

    # 调用 LLM 生成各维度的总结论
    llm_fac = llm_factory or LLMFactory()
    dim_summaries = _generate_dimension_summaries(final_dim_map, llm_fac)

    dim_headers = {
        "流动性维度": "### 【流动性维度】（货币与信用）",
        "宏观经济维度": "### 【宏观经济维度】（景气度与通胀）",
        "估值维度": "### 【估值维度】（绝对估值与风险溢价）",
        "资金面维度": "### 【资金面维度】（微观筹码与偏向）",
        "技术面维度": "### 【技术面维度】（趋势与量价时钟）",
        "情绪与期权面维度": "### 【情绪与期权面维度】（极端避险与恐慌）"
    }

    # 动态计算实际演算指标项数（不再硬编码"25 项"）：
    # 优先用数据源 indicators 列表长度，兜底用各维度已整理行数之和，确保报告正文的指标数量与真实运算一致。
    total_indicator_count = len(indicators) if indicators else sum(len(v) for v in final_dim_map.values())

    chapter_intro = (
        "## 二、择时六面图\n\n"
        f"> **量化择时体系 (过去 {hours_back:.1f} 小时时间窗口)**：本章节参照《择时六面图》研报框架，对流动性、宏观经济、估值、资金面、技术面及情绪期权面进行 {total_indicator_count} 项无未来函数信号演算。"
    )
    if "RADAR_CHART" in chart_paths_map:
        chapter_intro += f"\n\n![择时六维雷达图]({chart_paths_map['RADAR_CHART']})"

    try:
        from app.timing_hexagon.plotter import format_weighted_score_markdown_line
        score_line = format_weighted_score_markdown_line()
        chapter_intro += f"\n\n{score_line}"
    except Exception as e_score:
        app_logger.error(f"无法生成维度加权得分行: {e_score}")
        raise RuntimeError(f"[SynthesizerAgent] 维度加权得分行生成失败: {e_score}") from e_score

    chapter_sections = [chapter_intro]

    for dim_key, header in dim_headers.items():
        lines = final_dim_map.get(dim_key, [])
        ind_text = "\n\n".join(lines)
        if dim_key not in dim_summaries:
            app_logger.error(f"LLM 未返回维度 {dim_key} 的总结论")
            raise ValueError(f"[SynthesizerAgent] LLM 未返回维度 {dim_key} 的总结论")
        summary_text = dim_summaries[dim_key]
        dim_section = f"{header}\n\n{ind_text}\n\n**总结论**：{summary_text}"
        chapter_sections.append(dim_section)

    return "\n\n".join(chapter_sections)


def format_sector_summary_layout(summary_text: str) -> str:
    """
    对板块资讯总结 Markdown 进行标准化排版整理，严格满足：
    1. 整体结论/关键事件 标题与后续主要内容之间分行 (双换行 \n\n)
    2. 整体结论 与 关键事件 章节之间分行 (\n\n)
    3. 关键事件 里面的每一个具体事件之间分行 (\n\n)
    """
    if not summary_text:
        return summary_text

    text = summary_text.strip()
    
    # 规范标题格式
    text = re.sub(r'#*\s*【?整体结论】?:?', '#### 【整体结论】', text)
    text = re.sub(r'#*\s*【?关键事件】?:?', '#### 【关键事件】', text)

    if "#### 【整体结论】" in text and "#### 【关键事件】" in text:
        parts = text.split("#### 【整体结论】", 1)
        rest = parts[1].strip()
        c_parts = rest.split("#### 【关键事件】", 1)
        overall_content = c_parts[0].strip()
        events_content = c_parts[1].strip()
        
        # 解析关键事件列表，确保每个事件之间单独换行 (\n\n)
        raw_lines = events_content.split('\n')
        events = []
        current_event = []
        
        for line in raw_lines:
            s_line = line.strip()
            if not s_line:
                continue
            is_new = bool(re.match(r'^(\d+[\.\、]|[-*•])\s*', s_line))
            if is_new and current_event:
                events.append(" ".join(current_event))
                current_event = [s_line]
            else:
                current_event.append(s_line)
        if current_event:
            events.append(" ".join(current_event))
            
        formatted_events = "\n\n".join(events) if events else events_content
        
        return (
            f"#### 【整体结论】\n\n"
            f"{overall_content}\n\n"
            f"#### 【关键事件】\n\n"
            f"{formatted_events}"
        )

    text = text.replace("#### 【整体结论】", "#### 【整体结论】\n\n")
    text = text.replace("#### 【关键事件】", "\n\n#### 【关键事件】\n\n")
    return text


def build_sector_analysis_markdown_chapter(sector_results: List[SectorAnalysisResult]) -> str:
    """
    生成【## 三、资讯分析】 Markdown 章节 (直拼各板块 Analyst Agent 总结，100% 完整保留)
    """
    if not sector_results:
        return "## 三、资讯分析\n\n*过去时间窗口内暂无新增资讯分析板块*"

    sections = ["## 三、资讯分析"]
    for res in sector_results:
        bias_str = res.sentiment_bias.value if hasattr(res.sentiment_bias, 'value') else str(res.sentiment_bias)
        formatted_sum = format_sector_summary_layout(res.summary)
        sect_md = (
            f"### {res.sector_name} (资讯整体情绪: {bias_str})\n\n"
            f"{formatted_sum}"
        )
        sections.append(sect_md)

    return "\n\n".join(sections)


class SynthesizerAgent:
    """
    Synthesizer Agent：首席策略分析师 / 投研主编智能体 (直拼架构核心)
    """
    def __init__(self, llm_factory: Optional[LLMFactory] = None):
        self.llm_factory = llm_factory or LLMFactory()
        self.llm = self.llm_factory.get_llm()

    def _repair_json_string(self, text: str) -> str:
        """JSON 自动修补辅助函数"""
        clean_text = text.strip()
        if "```json" in clean_text:
            clean_text = clean_text.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```")[1].split("```")[0].strip()

        start_idx = clean_text.find('{')
        if start_idx != -1:
            clean_text = clean_text[start_idx:]

        end_idx = clean_text.rfind('}')
        if end_idx != -1:
            clean_text = clean_text[:end_idx + 1]
        else:
            clean_text += '}'

        clean_text = re.sub(r',\s*\}', '}', clean_text)
        clean_text = re.sub(r',\s*\]', ']', clean_text)
        return clean_text

    def synthesize_report(
        self,
        sector_results: List[SectorAnalysisResult],
        market_features: Dict[str, Any],
        hours_back: Optional[float] = None
    ) -> SynthesizedReportResult:
        """
        主编全局报告直拼合成主入口：
        1. 渲染【## 二、择时六面图】 (代码固定输出指标 + LLM 总结论)
        2. 渲染【## 三、资讯分析】 (代码直拼各板块总结，100% 无损)
        3. 调用 LLM 生成【## 一、总评】 (专精策略总揽、风险警示与跨行业推演)
        4. 代码纯文本直拼全篇研报 Markdown
        """
        if hours_back is None:
            hours_back = settings.REPORT_HOURS_BACK
        log_agent_action("SynthesizerAgent", "Synthesizing Report (Direct Assembly)", f"Sector Count: {len(sector_results)}, Hours Back: {hours_back}")

        today_str = datetime.date.today().strftime("%Y年%m月%d日")

        # 1. 渲染第二章：择时六面图
        ch2_timing_md = build_timing_hexagon_markdown_chapter(
            market_features,
            hours_back=hours_back,
            llm_factory=self.llm_factory
        )

        # 2. 渲染第三章：资讯分析
        ch3_news_md = build_sector_analysis_markdown_chapter(sector_results)

        # 3. 动态从 skills 目录加载 premarket-audio-analysis 技能指导
        skill_prompt = SkillLoader.load_skill_prompt("premarket-audio-analysis")

        # 构造给 CIO LLM 生成第一章【总评】的输入
        user_prompt = (
            f"【今日日期】: {today_str}\n\n"
            f"【时间窗口说明】: 本次研报仅分析过去 {hours_back:.1f} 小时内的增量数据与市场特征。\n\n"
            f"以下是已渲染好的【第二章 择时六面图】量化信号与【第三章 资讯分析】板块总结，请仔细审阅：\n\n"
            f"{ch2_timing_md}\n\n"
            f"{ch3_news_md}\n\n"
            f"请根据上述量化信号与板块资讯，撰写第一章【## 一、总评】内容，按系统提示词规定的 JSON 格式输出。"
        )
        prompt = f"{SYNTHESIZER_SYSTEM_PROMPT}\n\n{skill_prompt}\n\n{user_prompt}"

        try:
            response_text = self.llm_factory.invoke_with_circuit_breaker(self.llm, prompt)
            clean_json_str = self._repair_json_string(response_text)
            data = json.loads(clean_json_str)

            required_fields = [
                "report_title",
                "macro_executive_summary",
                "key_macro_alerts",
                "cross_sector_chains",
                "resolved_conflicts",
                "asset_allocation_advice",
            ]
            missing = [f for f in required_fields if f not in data or not data[f]]
            if missing:
                app_logger.error(f"[SynthesizerAgent] LLM 返回 JSON 缺少必需字段: {missing}")
                raise ValueError(f"[SynthesizerAgent] LLM 返回 JSON 缺少必需字段: {missing}")

            title = data["report_title"]
            exec_summary = data["macro_executive_summary"]
            alerts = data["key_macro_alerts"]
            chains = data["cross_sector_chains"]
            conflicts = data["resolved_conflicts"]
            advice = data["asset_allocation_advice"]

            # 4. 代码确定性直拼全篇研报 Markdown (100% 格式稳定、零丢包)
            alerts_formatted = "\n".join([f"- [风险警示] {a}" for a in alerts])
            chains_formatted = "\n".join([f"- [传导链条] {c}" for c in chains])

            ch1_total = (
                f"## 一、总评\n\n"
                f"{exec_summary}\n\n"
                f"### 核心风险警示与跨行业传导要点\n\n"
                f"{alerts_formatted}\n\n"
                f"{chains_formatted}\n\n"
                f"### 冲突消解与辩证归因说明\n\n"
                f"{'; '.join(conflicts)}\n\n"
                f"### 大类资产配置与仓位建议\n\n"
                f"{advice}"
            )

            full_report_md = (
                f"# {title}\n\n"
                f"{ch1_total}\n\n"
                f"{ch2_timing_md}\n\n"
                f"{ch3_news_md}"
            )

            result = SynthesizedReportResult(
                report_title=title,
                generation_date=datetime.date.today().isoformat(),
                sector_count=len(sector_results),
                macro_executive_summary=exec_summary,
                key_macro_alerts=alerts,
                cross_sector_chains=chains,
                resolved_conflicts=conflicts,
                full_report_markdown=full_report_md
            )

            app_logger.info(f"✅ [Synthesizer Agent] 成功完成直拼式全局综合研报合成 (标题: {result.report_title})")
            return result

        except Exception as e:
            app_logger.error(f"❌ [Synthesizer Agent] 全局研报合成解析异常: {e}")
            raise RuntimeError(f"[Synthesizer Agent] 全局研报合成失败: {e}") from e


def format_market_features_prompt(market_features: Dict[str, Any]) -> str:
    """整理全市场特征算子与择时信号给主编的提示段落"""
    if not market_features:
        return "【全市场资金与宏观环境】: 暂无。"

    ops = market_features.get("operators", {})
    lev = ops.get("leverage_capital", {})
    macro = ops.get("macro_liquidity", {})
    val = ops.get("valuation_and_breadth", {})

    return (
        f"【全市场金融资金与宏观环境 (供第一章总评与第二章择时六面图使用)】:\n"
        f"- 两融资金情绪: 交易占比 {round(lev.get('margin_trading_ratio', 0.0)*100, 2)}% | 净融资买入占比 {round(lev.get('net_margin_buy_ratio', 0.0)*100, 2)}%\n"
        f"- 宏观货币流动性: Shibor 7D 利差 {macro.get('liquidity_spread', 0.0)}% | M2-M1 剪刀差 {macro.get('m2_m1_scissors_difference', 0.0)}% | PMI {macro.get('pmi_manufacturing', 50.0)}\n"
        f"- 估值与微观结构: ERP {val.get('equity_risk_premium_erp', 0.0)}% | 全 A PE {val.get('market_pe', 0.0)} | 炸板率 {round(val.get('zhaban_rate', 0.0)*100, 2)}%"
    )
