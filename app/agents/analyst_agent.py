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
你的任务是根据特定行业/主题板块归拢的精炼情报卡片，撰写简明扼要的行业资讯总结。

【严格注意事项】：
1. **严禁引入任何金融数据**（如两融交易占比、Shibor、ERP、炸板率等量化金融指标）。
2. **只输出板块资讯总结 (summary)**：用 1~2 段简明扼要的话总结该板块近期发生的核心事件、行业动态及资讯走势，不要输出具体的长文本清单或逐条新闻列表。

【输出格式要求】：
你必须且只能输出严格的 JSON 格式对象，结构如下：
{
  "sentiment_bias": "看多",  // 只能为 "看多", "看空", "中性" 之一
  "summary": "这是该板块近期的整体资讯总结..."
}
"""


class AnalystAgent:
    """
    Analyst Agent：纯资讯板块分析智能体
    """
    def __init__(self, llm_factory: Optional[LLMFactory] = None, model_tier: str = "flash"):
        self.llm_factory = llm_factory or LLMFactory(request_timeout=30.0, max_retries=3)
        self.model_tier = model_tier.lower()
        if self.model_tier == "pro":
            self.llm = self.llm_factory.get_pro_llm()
        else:
            self.llm = self.llm_factory.get_flash_llm()

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

    def _fallback_analysis(self, sector_name: str, cards: List[Dict[str, Any]]) -> SectorAnalysisResult:
        """纯资讯降级硬规则抽取器"""
        count = len(cards)
        if not cards:
            return SectorAnalysisResult(
                sector_name=sector_name,
                card_count=0,
                sentiment_bias=SentimentType.NEUTRAL,
                summary=f"过去时间窗口内，【{sector_name}】板块暂无新增重要资讯。"
            )

        bullish_count = sum(1 for c in cards if c.get("sentiment") == "看多")
        bearish_count = sum(1 for c in cards if c.get("sentiment") == "看空")

        if bullish_count > bearish_count:
            bias = SentimentType.BULLISH
        elif bearish_count > bullish_count:
            bias = SentimentType.BEARISH
        else:
            bias = SentimentType.NEUTRAL

        sample_titles = [c.get("title", "") for c in cards[:2] if c.get("title")]
        title_str = "；".join(sample_titles) if sample_titles else "突发行业动态"

        summary_text = (
            f"本分析窗口内共监测到 {count} 条相关行业资讯，整体资讯情绪偏向为【{bias.value}】。"
            f"核心关注事件包括：{title_str}。行业技术突破与产业链共振推进。"
        )

        return SectorAnalysisResult(
            sector_name=sector_name,
            card_count=count,
            sentiment_bias=bias,
            summary=summary_text
        )

    def analyze_sector(
        self,
        sector_name: str,
        cards: List[Dict[str, Any]],
        market_features: Optional[Dict[str, Any]] = None,
        hours_back: float = 1.0
    ) -> SectorAnalysisResult:
        """
        对指定板块卡片进行纯资讯总结分析
        """
        if not cards:
            return self._fallback_analysis(sector_name, [])

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
            app_logger.warning(f"⚠️ [Analyst Agent] 纯资讯总结解析异常 ({e})，切入硬规则降级。")
            return self._fallback_analysis(sector_name, cards)


def load_default_market_features() -> Dict[str, Any]:
    """保留兼容性接口"""
    return {}


def format_market_features_prompt(market_features: Dict[str, Any]) -> str:
    """保留兼容性接口"""
    return ""
