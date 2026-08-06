"""
第三层 Analyst Agent (行业/主题资讯分析智能体)
========================================================================
职责：纯粹基于特定行业/主题板块在指定时间窗口内归拢的精炼情报卡片进行资讯分析。
严禁引入任何金融数据（如两融交易占比、Shibor、ERP等）。

输出格式：
每个板块只输出简明极简的板块资讯总结 (summary)，不包含一句话新闻列表。
"""
import json
import re
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from app.core.logger import app_logger, log_agent_action
from app.core.config import settings
from app.core.llm_factory import LLMFactory
from app.models.news_schema import SentimentType


class SectorAnalysisResult(BaseModel):
    """
    Analyst Agent 单板块纯资讯分析结果模型 (精简版：仅保留资讯总结)
    """
    sector_name: str = Field(..., description="板块/物理簇名称 (如 半导体芯片, 人工智能大模型)")
    card_count: int = Field(0, description="参与分析的情报卡片总数")
    sentiment_bias: SentimentType = Field(SentimentType.NEUTRAL, description="板块综合资讯情绪: 看多 / 看空 / 中性")
    summary: str = Field(..., description="板块近期资讯的简明综合总结")


ANALYST_SYSTEM_PROMPT = """你是一位资深的买方金融投研【资讯分析师】。
你的任务是根据特定行业/主题板块归拢的精炼情报卡片，撰写一份既有【整体趋势研判结论】又有【核心事件事实支撑】的高质量行业资讯总结。

【核心撰写要求】：
1. **整体研判结论先行**：在总结开头用简练语言给出该板块的整体资讯研判与走势结论（如：“当前板块受‘技术突破与政策红利’驱动呈现偏积极走势”）。
2. **值得关注的核心事件事实**：明确提炼并总结近期发生的 2~3 个最值得关注的具体核心动态与事件事实（如：重要产品发布、政策落地、企业合作或产业链价格异动等），让读者能够清晰掌握发生了什么关键事实。
3. **严禁引入量化金融指标**：严禁引入两融占比、Shibor、ERP、炸板率等量化资金数据（此类指标由算子引擎统一处理）。

【输出格式要求】：
你必须且只能输出严格的 JSON 格式对象，结构如下：
{
  "sentiment_bias": "看多",  // 只能为 "看多", "看空", "中性" 之一
  "summary": "【整体结论】...\n【关键事件】\n1. ...\n2. ..."
}
"""


class AnalystAgent:
    """
    Analyst Agent：纯资讯板块分析智能体
    """
    def __init__(self, llm_factory: Optional[LLMFactory] = None):
        self.llm_factory = llm_factory or LLMFactory()
        self.llm = self.llm_factory.get_llm()

    def _repair_json_string(self, text: str) -> str:
        """JSON 自动修复辅助函数"""
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

    def analyze_sector(
        self,
        sector_name: str,
        cards: List[Dict[str, Any]],
        market_features: Optional[Dict[str, Any]] = None
    ) -> SectorAnalysisResult:
        """
        对指定板块卡片进行纯资讯总结分析
        """
        hours_back = settings.REPORT_HOURS_BACK
        if not cards:
            return SectorAnalysisResult(
                sector_name=sector_name,
                card_count=0,
                sentiment_bias=SentimentType.NEUTRAL,
                summary=f"过去时间窗口内，【{sector_name}】板块暂无新增重要资讯。"
            )

        log_agent_action("AnalystAgent", "Analyzing Sector News Summary", f"Sector: {sector_name}, Card Count: {len(cards)}")

        card_summaries = []
        for idx, c in enumerate(cards[:20], 1):
            card_summaries.append(
                f"新闻[{idx}]: {c.get('title', '')}\n"
                f"  - 核心事实: {'; '.join(c.get('core_facts', []))}\n"
                f"  - 涉及实体: {', '.join(c.get('entities', []))}\n"
                f"  - 研报价值: {c.get('research_value', 1)}⭐ | 情绪: {c.get('sentiment', '中性')}"
            )
        cards_input = "\n\n".join(card_summaries)

        user_prompt = (
            f"【待分析板块】: {sector_name}\n\n"
            f"【归类情报卡片列表】({len(cards)}条):\n{cards_input}"
        )
        prompt = f"{ANALYST_SYSTEM_PROMPT}\n\n{user_prompt}"

        try:
            response_text = self.llm_factory.invoke_with_circuit_breaker(self.llm, prompt)
            clean_json_str = self._repair_json_string(response_text)
            data = json.loads(clean_json_str)

            sent_str = data.get("sentiment_bias", "中性")
            if sent_str not in ["看多", "看空", "中性"]:
                bias_enum = SentimentType.NEUTRAL
            else:
                bias_enum = SentimentType(sent_str)

            result = SectorAnalysisResult(
                sector_name=sector_name,
                card_count=len(cards),
                sentiment_bias=bias_enum,
                summary=data.get("summary", f"【{sector_name}板块资讯总结】已完成提炼。")
            )

            app_logger.info(f"✅ [Analyst Agent] 成功完成纯资讯板块总结 ({sector_name}, 情绪偏向: {result.sentiment_bias.value})")
            return result

        except Exception as e:
            app_logger.error(f"❌ [Analyst Agent] 纯资讯总结解析异常: {e}")
            raise e
