"""
Extractor Agent (信息萃取与价值评级智能体)
职责单一：
1. 专注于从原始财经新闻中高密度萃取客观事实、核心实体、关键量化指标
2. 进行情绪方向研判 (看多/看空/中性) 与情绪偏向分值 (-1.0 至 +1.0)
3. 评估研报价值星级 (1-5星) 与市场短期冲击烈度 (1-5级)
4. 严格剥离板块分类与打标职责（分类打标由独立的 TaggerAgent 执行）
"""
import re
import json
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from app.core.logger import app_logger, log_agent_action
from app.core.llm_factory import LLMFactory
from app.models.news_schema import SentimentType


class ExtractionResult(BaseModel):
    """摘要萃取智能体标准化输出结果"""
    core_facts: List[str] = Field(default_factory=list, description="提取的核心客观事实列表 (1~3条，简明扼要)")
    entities: List[str] = Field(default_factory=list, description="提取的关键实体列表 (公司/机构/产业/产品)")
    key_metrics: Dict[str, Any] = Field(default_factory=dict, description="提取的关键量化指标键值对 (如 营收、同比、利率等)")
    sentiment: SentimentType = Field(SentimentType.NEUTRAL, description="情绪倾向: 看多 / 看空 / 中性")
    sentiment_score: float = Field(0.0, description="情绪得分 (-1.0 极度看空 至 +1.0 极度看多)")
    research_value: int = Field(1, ge=1, le=5, description="研报价值评级 (1-5星)")
    impact_rating: int = Field(1, ge=1, le=5, description="市场冲击烈度 (1-5级)")


EXTRACTOR_SYSTEM_PROMPT = """你是一位资深的买方金融投研分析师与数据萃取专家。
你的唯一任务是：从给定的原始财经新闻/快讯文本中，高密度、客观、无幻觉地提炼事实、实体、量化指标并进行深度评级打分。

请严格遵守以下萃取与打分规则：

1. 【核心事实 (core_facts)】：从文本中提炼 1~3 条最核心的客观事实陈述，要求精炼无废话，严格基于原文，拒绝主观揣测。
2. 【实体识别 (entities)】：精准提取新闻中涉及的核心实体（上市公司名称、核心产业、监管机构、关键人物或重点产品）。
3. 【关键量化指标 (key_metrics)】：精准提取文本中出现的所有关键量化数据（如：增减幅度、营收/利润金额、产品单价、产能规模、利率指标等），格式为键值对字典（如 `{"净利润": "15.8亿元", "同比增速": "+35.2%"}`），若无量化指标则返回 `{}`。
4. 【情绪方向与得分 (sentiment & sentiment_score)】：
   - sentiment: 只能为 "看多"、"看空"、"中性" 之一。
   - sentiment_score: -1.0 (极度利空) 至 +1.0 (极度利多) 之间的实数。若为常规无明显倾向的新闻或符合预期的例行公告，情绪为"中性"，得分为 0.0。
5. 【研报价值评级 (research_value, 1-5星)】：
   - 5星：重大会议/央行货币政策转向、颠覆性核心技术突破、重大突发地缘事件。
   - 4星：行业重磅政策、头部公司财报显著超/低于预期、百亿级重大产业并购。
   - 3星：常规行业政策动态、重点个股业绩公告、盘中大类资产显著波动。
   - 2星：次要公司日常动态、常规市场日常点评。
   - 1星：日常噪音、营销广告或低价值快讯。
6. 【市场冲击级别 (impact_rating, 1-5级)】：评估该新闻在 24-48 小时内对相关资产价格或市场情绪的冲击烈度（1为微弱，5为剧烈冲击）。

【输出格式要求】：
必须且只能输出严格的纯 JSON 对象，格式如下：
{
  "core_facts": ["事实陈述1", "事实陈述2"],
  "entities": ["实体1", "实体2"],
  "key_metrics": {"营收": "100亿元", "同比": "+15.2%"},
  "sentiment": "看多",
  "sentiment_score": 0.65,
  "research_value": 4,
  "impact_rating": 3
}
"""


class ExtractorAgent:
    """
    Extractor Agent：负责纯粹的信息萃取、事实提炼、量化指标提取与价值评级
    """
    def __init__(self, llm_factory: Optional[LLMFactory] = None):
        self.llm_factory = llm_factory or LLMFactory()
        self.llm = self.llm_factory.get_llm()

    def _repair_json_string(self, text: str) -> str:
        """强化版 JSON 字符串修补与清洗代码"""
        clean_text = text.strip()

        # 1. 剥离 Markdown 代码块包裹
        if "```json" in clean_text:
            clean_text = clean_text.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```")[1].split("```")[0].strip()

        # 2. 查找首个 '{' 和最后一个 '}'
        start_idx = clean_text.find('{')
        if start_idx != -1:
            clean_text = clean_text[start_idx:]

        # 3. 若结尾缺少 '}' 则修补补齐
        end_idx = clean_text.rfind('}')
        if end_idx != -1:
            clean_text = clean_text[:end_idx + 1]
        else:
            clean_text += '}'

        # 4. 修复尾随逗号
        clean_text = re.sub(r',\s*\}', '}', clean_text)
        clean_text = re.sub(r',\s*\]', ']', clean_text)

        return clean_text

    def _parse_llm_json_response(self, response_text: str) -> ExtractionResult:
        """从 LLM 返回的文本中提取并解析 ExtractionResult"""
        try:
            clean_json_str = self._repair_json_string(response_text)
            data = json.loads(clean_json_str)

            # 校验必需字段
            required_fields = ["sentiment", "research_value", "impact_rating", "sentiment_score"]
            missing = [f for f in required_fields if f not in data or data[f] is None]
            if missing:
                app_logger.error(f"[Extractor Agent] LLM 返回 JSON 缺少必需字段: {missing}")
                raise ValueError(f"[Extractor Agent] LLM 返回 JSON 缺少必需字段: {missing}")

            # 校验情绪枚举
            sentiment_str = data["sentiment"]
            if sentiment_str not in ["看多", "看空", "中性"]:
                app_logger.error(f"[Extractor Agent] LLM 返回非法情绪枚举: {sentiment_str}")
                raise ValueError(f"Extractor Agent 返回非法情绪枚举: {sentiment_str}")
            sentiment_enum = SentimentType(sentiment_str)

            # 限制打分范围 (研报价值 1-5星, 冲击级别 1-5级, 情绪得分 -1.0 到 +1.0)
            research_val = max(1, min(5, int(data["research_value"])))
            impact_val = max(1, min(5, int(data["impact_rating"])))
            sent_score = max(-1.0, min(1.0, float(data["sentiment_score"])))

            return ExtractionResult(
                core_facts=data.get("core_facts") or [],
                entities=data.get("entities") or [],
                key_metrics=data.get("key_metrics") or {},
                sentiment=sentiment_enum,
                sentiment_score=sent_score,
                research_value=research_val,
                impact_rating=impact_val
            )
        except Exception as e:
            app_logger.error(f"[Extractor Agent] JSON 解析失败: {e}, 原始内容: {response_text[:200]}")
            raise ValueError(f"Extractor Agent JSON 解析失败: {e}")

    def extract(self, raw_news: Dict[str, Any]) -> ExtractionResult:
        """单篇新闻资讯抽取主入口"""
        news_id = raw_news.get("news_id", "unknown")
        content = raw_news.get("content", "")
        title = raw_news.get("title") or ""
        source = raw_news.get("source", "")
        
        user_prompt = f"新闻标题: {title}\n新闻正文: {content}\n新闻来源: {source}"
        log_agent_action("ExtractorAgent", "Extracting", f"news_id={news_id}")

        try:
            prompt = f"{EXTRACTOR_SYSTEM_PROMPT}\n\n【待分析新闻】:\n{user_prompt}"
            response_text = self.llm_factory.invoke_with_circuit_breaker(self.llm, prompt)
            
            result = self._parse_llm_json_response(response_text)
            app_logger.info(f"[Extractor Agent] 成功萃取事实与指标 (news_id={news_id}, 研报价值={result.research_value}星, 情绪={result.sentiment.value})")
            return result

        except Exception as e:
            app_logger.error(f"[Extractor Agent] 执行抽取异常: {e}")
            raise e

    def extract_batch(self, raw_news_list: List[Dict[str, Any]]) -> List[ExtractionResult]:
        """批量新闻资讯抽取接口"""
        results = []
        log_agent_action("ExtractorAgent", "BatchExtraction", f"Processing {len(raw_news_list)} items")
        for raw in raw_news_list:
            res = self.extract(raw)
            results.append(res)
        return results
