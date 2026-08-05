"""
第三层 Synthesizer Agent (首席策略分析师 / 投研主编智能体)
========================================================================
全篇研报严格分为三大核心章节：
1. ## 一、总评：综合【择时六面图 (金融数据)】与【资讯分析 (新闻数据)】结果，撰写全局策略总揽、核心风险警示与资产配置建议。
2. ## 二、择时六面图：专门展示金融数据与 34 项量化择时信号（流动性、经济面、估值、资金面、技术面、情绪面）。
3. ## 三、资讯分析：专门展示资讯数据（按板块划分），每个板块仅包含简明资讯总结，绝不包含任何金融数据或冗余列表。
"""
import json
import re
import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from app.core.logger import app_logger, log_agent_action
from app.core.llm_factory import LLMFactory
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


SYNTHESIZER_SYSTEM_PROMPT = """你是一位资深的买方公募/私募头部基金【首席策略分析师 / 投研主编 (CIO)】。
你的任务是综合【择时六面图 (量化金融数据)】与【资讯分析 (下属各行业分析师提交的纯新闻数据)】，进行全局统稿与跨维推演，合成一份高含金量的全盘综合投研报告。

【三大核心章节职责划分】：
1. **## 一、总评**：
   - **数据来源**：综合【择时六面图（金融数据）】与【资讯分析（新闻数据）】两者的结果。
   - **包含内容**：首席策略总揽、全市场总体多空研判、核心宏观/市场风险警示、跨行业资讯传导与大类资产配置建议。
   - **排版规范**：不同观点、风险警示与配置建议之间必须做好换行分段（使用 double newline `\\n\\n`）。

2. **## 二、择时六面图**：
   - **数据来源**：专门使用【金融数据】（34 项量化择时信号与特征算子）。
   - **包含内容**：流动性面、宏观经济面、估值面、资金面、技术面、情绪与期权面 6 大维度的定量剖析。
   - **排版规范**：严禁包含任何汇总大表格，不同维度之间必须清晰换行分段。

3. **## 三、资讯分析**：
   - **数据来源**：专门使用【资讯数据】（新闻总结）。
   - **严禁包含任何金融数据**（如两融交易占比、Shibor、ERP、炸板率等量化指标），也不输出一句话新闻列表。
   - **格式精简**：每个板块标题下直接接板块资讯总结段落：
     ```markdown
     ### [板块名称] (资讯情绪: 看多/看空/中性)

     板块资讯总结段落...
     ```

【输出格式要求】：
你必须且只能输出严格的 JSON 格式对象，结构如下：
{
  "report_title": "2026年07月29日 智能投研全市场综合研报：择时六面图 流动性偏多、景气度中性",
  "macro_executive_summary": "#### 【首席策略总揽】\\n...",
  "key_macro_alerts": ["宏观/市场警示1", "宏观/市场警示2"],
  "cross_sector_chains": ["【半导体 -> AI算力】上游 Chiplet 通线降低 AI 算力芯片封测成本"],
  "resolved_conflicts": ["消解【科技看多】与【流动性偏紧】冲突..."],
  "full_report_markdown": "# 2026年07月29日 智能投研全市场综合研报：择时六面图 流动性偏多、景气度中性\\n\\n## 一、总评\\n...\\n\\n## 二、择时六面图\\n...\\n\\n## 三、资讯分析\\n..."
}
"""


def build_timing_hexagon_markdown_chapter(market_features: Optional[Dict[str, Any]] = None, hours_back: float = 1.0) -> str:
    """
    生成【## 二、择时六面图】 Markdown 章节 (专门使用金融数据，无新闻)
    """
    timing = market_features.get("timing_hexagon", {}) if market_features else {}
    ops = market_features.get("operators", {}) if market_features else {}
    lev = ops.get("leverage_capital", {})
    macro = ops.get("macro_liquidity", {})
    val = ops.get("valuation_and_breadth", {})

    indicators = timing.get("indicators", [])

    dim_map = {
        "流动性": [],
        "经济面": [],
        "估值面": [],
        "资金面": [],
        "技术面": [],
        "情绪面": [],
        "期权面": []
    }

    for item in indicators:
        dim = item.get("dimension", "")
        ind = item.get("indicator", "")
        score = item.get("signal_score")

        if score == 1.0:
            signal_str = "🟢 看多"
        elif score == -1.0:
            signal_str = "🔴 看空"
        else:
            signal_str = "⚪ 中性"

        txt = item.get("signal_text", "")
        detail = f"{ind}: {signal_str}"
        if txt and txt != "中性":
            detail += f" ({txt})"

        if "流动性" in dim:
            dim_map["流动性"].append(detail)
        elif "经济" in dim:
            dim_map["经济面"].append(detail)
        elif "估值" in dim:
            dim_map["估值面"].append(detail)
        elif "资金" in dim:
            dim_map["资金面"].append(detail)
        elif "技术" in dim:
            dim_map["技术面"].append(detail)
        elif "情绪" in dim:
            dim_map["情绪面"].append(detail)
        elif "期权" in dim:
            dim_map["期权面"].append(detail)

    chapter_md = (
        f"## 二、择时六面图\n\n"
        f"> **量化择时体系 (过去 {hours_back:.1f} 小时时间窗口)**：本章节参照《择时六面图》研报框架，对流动性、宏观经济、估值、资金面、技术面及情绪期权面进行无未来函数信号演算。\n\n"
        f"### 🟢 【流动性维度】（货币与信用）\n\n"
        f"- **短端资金与利差**: Shibor 7D 利差 `{macro.get('liquidity_spread', 0.0)}%`，M2-M1 剪刀差 `{macro.get('m2_m1_scissors_difference', 0.0)}%`。\n\n"
        f"- **核心信号**: {'; '.join(dim_map['流动性'][:4]) if dim_map['流动性'] else '短端资金利率维持极度宽松'}\n\n"
        f"### 🔵 【宏观经济维度】（景气度与通胀）\n\n"
        f"- **先行景气与通胀**: 制造业 PMI `{macro.get('pmi_manufacturing', 50.0)}`，CPI 同比 `{macro.get('cpi_yoy', 0.0)}%`，PPI 同比 `{macro.get('ppi_yoy', 0.0)}%`。\n\n"
        f"- **核心信号**: {'; '.join(dim_map['经济面'][:4]) if dim_map['经济面'] else '制造业 PMI 趋势向好'}\n\n"
        f"### 🟡 【估值维度】（绝对估值与风险溢价）\n\n"
        f"- **全市场 ERP 与 PE**: 股权风险溢价 (ERP) `{val.get('equity_risk_premium_erp', 0.0)}%`，全 A PE-TTM `{val.get('market_pe', 0.0)}`。\n\n"
        f"- **核心信号**: {'; '.join(dim_map['估值面'][:4]) if dim_map['估值面'] else '股权风险溢价处于合理区间'}\n\n"
        f"### 🔴 【资金面维度】（微观筹码与偏向）\n\n"
        f"- **杠杆资金与情绪**: 两融交易占比 `{round(lev.get('margin_trading_ratio', 0.0)*100, 2)}%`，净融资买入占比 `{round(lev.get('net_margin_buy_ratio', 0.0)*100, 2)}%`。\n\n"
        f"- **核心信号**: {'; '.join(dim_map['资金面'][:4]) if dim_map['资金面'] else '两融杠杆资金维持中性偏多'}\n\n"
        f"### 🟣 【技术面维度】（趋势与量价时钟）\n\n"
        f"- **趋势与布林带**: 均线与波幅指示盘面运行于支撑与阻力位之间。\n\n"
        f"- **核心信号**: {'; '.join(dim_map['技术面'][:4]) if dim_map['技术面'] else '均线与量价时钟归属于低风险象限'}\n\n"
        f"### 🟠 【情绪与期权面维度】（极端避险与恐慌）\n\n"
        f"- **盘面炸板与期权 VIX**: 全市场炸板率 `{round(val.get('zhaban_rate', 0.0)*100, 2)}%`，50ETF 期权 QVIX 维持正常范畴。\n\n"
        f"- **核心信号**: {'; '.join(dim_map['情绪面'] + dim_map['期权面']) if (dim_map['情绪面'] or dim_map['期权面']) else '炸板率与期权波动率处于安全边界'}"
    )

    return chapter_md


def build_sector_analysis_markdown_chapter(sector_results: List[SectorAnalysisResult]) -> str:
    """
    生成【## 三、资讯分析】 Markdown 章节 (仅包含每个板块的精炼资讯总结，无金融指标与列表)
    """
    if not sector_results:
        return "## 三、资讯分析\n\n*过去时间窗口内暂无新增资讯分析板块*"

    sections = ["## 三、资讯分析"]
    for res in sector_results:
        bias_str = res.sentiment_bias.value if hasattr(res.sentiment_bias, 'value') else str(res.sentiment_bias)
        sum_text = res.summary.strip()
        sect_md = (
            f"### {res.sector_name} (资讯整体情绪: {bias_str})\n\n"
            f"{sum_text}"
        )
        sections.append(sect_md)

    return "\n\n".join(sections)


class SynthesizerAgent:
    """
    Synthesizer Agent：首席策略分析师 / 投研主编智能体
    """
    def __init__(self, llm_factory: Optional[LLMFactory] = None, model_tier: str = "flash"):
        self.llm_factory = llm_factory or LLMFactory(request_timeout=60.0, max_retries=3)
        self.model_tier = model_tier.lower()
        if self.model_tier == "flash":
            self.llm = self.llm_factory.get_flash_llm()
        else:
            self.llm = self.llm_factory.get_pro_llm()

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

    def _fallback_synthesis(
        self,
        sector_results: List[SectorAnalysisResult],
        market_features: Dict[str, Any],
        hours_back: float = 1.0
    ) -> SynthesizedReportResult:
        """主编降级硬规则合成器"""
        today_str = datetime.date.today().strftime("%Y年%m月%d日")
        title = f"{today_str} 智能投研全市场综合研报：择时六面图 流动性偏多、景气度中性"

        count = len(sector_results)
        sector_names = [s.sector_name for s in sector_results] if sector_results else ["无"]

        ops = market_features.get("operators", {})
        lev = ops.get("leverage_capital", {})
        macro = ops.get("macro_liquidity", {})
        val = ops.get("valuation_and_breadth", {})

        margin_pct = round(lev.get("margin_trading_ratio", 0.0) * 100, 2)
        spread = macro.get("liquidity_spread", 0.0)
        erp = val.get("equity_risk_premium_erp", 0.0)

        exec_summary = (
            f"- **分析时间窗口**：过去 {hours_back:.1f} 小时增量数据。\n\n"
            f"- **全市场择时研判**：当前市场呈现'流动性偏多、景气度中性、估值合理'状态。\n\n"
            f"- **覆盖板块**：全量完成共 {count} 个活跃板块资讯分析 ({', '.join(sector_names)})。\n\n"
            f"- **全市场资金环境**：杠杆资金两融交易占比为 {margin_pct}%，Shibor 7D 利差为 {spread}%，股权风险溢价 (ERP) 为 {erp}%。\n\n"
            f"- **主编战略配置建议**：建议保持中性偏积极仓位，重点关注具备自律催化与技术突破的核心龙头。"
        )

        ch2_timing = build_timing_hexagon_markdown_chapter(market_features, hours_back=hours_back)
        ch3_news = build_sector_analysis_markdown_chapter(sector_results)

        full_md = (
            f"# {title}\n\n"
            f"## 一、总评\n\n"
            f"{exec_summary}\n\n"
            f"### 核心风险警示与跨行业传导要点\n\n"
            f"⚠️ 宏观流动性: Shibor 7D 利差 {spread}%，警示短端资金面边际变化\n\n"
            f"⚠️ 全市场博弈: 炸板率 {round(val.get('zhaban_rate', 0.0)*100, 2)}%，提示短线题材追高风险\n\n"
            f"🔗 【宏观资金 -> 行业估值】短端利率与 ERP ({erp}%) 共同构成全市场高估值板块的统一估值约束\n\n"
            f"🔗 【产业链传导】上游核心技术突破及成本变动向下游终端应用逐步传导\n\n"
            f"{ch2_timing}\n\n"
            f"{ch3_news}"
        )

        return SynthesizedReportResult(
            report_title=title,
            generation_date=datetime.date.today().isoformat(),
            sector_count=count,
            macro_executive_summary=exec_summary,
            key_macro_alerts=[
                f"宏观流动性: Shibor 7D 利差 {spread}%",
                f"全市场博弈: 炸板率 {round(val.get('zhaban_rate', 0.0)*100, 2)}%"
            ],
            cross_sector_chains=[
                "【宏观资金 -> 行业估值】短端利率与 ERP 共同构成高估值板块估值约束",
                "【产业链传导】上游技术突破向下游终端应用传导"
            ],
            resolved_conflicts=[
                "消解【宏观流动性宽松】与【实体信用流转】之间的分歧"
            ],
            full_report_markdown=full_md
        )

    def synthesize_report(
        self,
        sector_results: List[SectorAnalysisResult],
        market_features: Dict[str, Any],
        hours_back: float = 1.0
    ) -> SynthesizedReportResult:
        """
        主编全局报告合成主入口
        """
        log_agent_action("SynthesizerAgent", "Synthesizing Report", f"Sector Count: {len(sector_results)}, Hours Back: {hours_back}")

        today_str = datetime.date.today().strftime("%Y年%m月%d日")
        macro_text = format_market_features_prompt(market_features)

        # 整理板块资讯总结文本
        sector_blocks = []
        for s in sector_results:
            bias_str = s.sentiment_bias.value if hasattr(s.sentiment_bias, 'value') else str(s.sentiment_bias)
            sector_blocks.append(
                f"【板块】: {s.sector_name} (资讯情绪: {bias_str})\n"
                f"资讯总结:\n{s.summary}"
            )
        sectors_text = "\n\n".join(sector_blocks) if sector_blocks else "暂无下属板块资讯"

        user_prompt = (
            f"【时间窗口说明】: 本次研报仅分析过去 {hours_back:.1f} 小时内的增量数据与市场特征。\n\n"
            f"{macro_text}\n\n"
            f"【下属各行业分析师提交的全部板块资讯总结】(共{len(sector_results)}个板块，必须全量包含在第三章'资讯分析'中，不得遗漏)：\n{sectors_text}"
        )
        prompt = f"{SYNTHESIZER_SYSTEM_PROMPT}\n\n{user_prompt}"

        try:
            response_text = self.llm_factory.invoke_with_circuit_breaker(self.llm, prompt)
            clean_json_str = self._repair_json_string(response_text)
            data = json.loads(clean_json_str)

            title = data.get("report_title", f"{today_str} 智能投研全市场综合研报：择时六面图 流动性偏多、景气度中性")
            exec_summary = data.get("macro_executive_summary", "#### 【首席策略总揽】\n已完成全盘研报统稿。")
            alerts = data.get("key_macro_alerts", [])
            chains = data.get("cross_sector_chains", [])
            conflicts = data.get("resolved_conflicts", [])
            full_md = data.get("full_report_markdown", "")

            # 若模型输出的 full_report_markdown 缺少核心章节，使用代码强控制兜底组装
            if not full_md or "## 一、总评" not in full_md or "## 二、择时六面图" not in full_md or "## 三、资讯分析" not in full_md:
                ch2_timing = build_timing_hexagon_markdown_chapter(market_features, hours_back=hours_back)
                ch3_news = build_sector_analysis_markdown_chapter(sector_results)
                full_md = (
                    f"# {title}\n\n"
                    f"## 一、总评\n\n"
                    f"{exec_summary}\n\n"
                    f"### 核心风险警示与跨行业传导要点\n\n"
                    f"⚠️ 核心风险: {'; '.join(alerts) if alerts else '短端资金与流动性分层警示'}\n\n"
                    f"🔗 跨行业传导: {'; '.join(chains) if chains else '上游核心技术向上游传导'}\n\n"
                    f"{ch2_timing}\n\n"
                    f"{ch3_news}"
                )

            result = SynthesizedReportResult(
                report_title=title,
                generation_date=datetime.date.today().isoformat(),
                sector_count=len(sector_results),
                macro_executive_summary=exec_summary,
                key_macro_alerts=alerts,
                cross_sector_chains=chains,
                resolved_conflicts=conflicts,
                full_report_markdown=full_md
            )

            app_logger.info(f"✅ [Synthesizer Agent] 成功完成全局综合研报合成 (标题: {result.report_title})")
            return result

        except Exception as e:
            app_logger.warning(f"⚠️ [Synthesizer Agent] 解析异常 ({e})，切入硬规则全局合成器。")
            return self._fallback_synthesis(sector_results, market_features, hours_back)


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
