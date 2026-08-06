"""
Extractor Agent (信息萃取智能体) - 8月4日功能增强版
实现子任务：
1. 封装 ExtractorAgent 类，支持模型分级 (Flash / Pro)
2. 强化 JSON 自动修补与容错防爆机制 (修复截断、缺失括号、非规范字符)
3. 提供批量资讯提取 `extract_batch()` 与强类型 StructuredNewsSchema 对象转化
"""
import re
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from app.core.logger import app_logger, log_agent_action
from app.core.llm_factory import LLMFactory
from app.models.news_schema import StructuredNewsSchema, SentimentType, EventType


EXTRACTOR_SYSTEM_PROMPT = """你是一位资深的买方金融投研分析师与数据萃取专家。
你的任务是从给定的原始财经新闻/快讯文本中，高密度、无幻觉地提炼结构化情报卡片。

请严格遵守以下萃取与打分规则：
1. 【核心事实 (core_facts)】：从文本中提取 1~3 条最关键的客观事实陈述，要求精炼无废话，严格基于原文事实，拒绝主观推测。
2. 【实体识别 (entities)】：精准提取新闻中涉及的核心实体（股票/公司名称、产业/产业链、政府/监管机构、核心产品或关键人物）。
3. 【关键量化指标 (key_metrics)】：精准提取文本中出现的所有关键量化数据（如：增减幅度、营收/利润金额、产品价格、产能、利率、估值等），格式为键值对字典（如 `{"营收": "100亿元", "同比": "+15.2%"}`），若无则返回 `{}`。
4. 【情绪方向与得分 (sentiment & sentiment_score)】：
   - sentiment: 只能为 "看多"、"看空"、"中性" 之一。
   - sentiment_score: -1.0 (极度利空) 至 +1.0 (极度利多) 之间的实数。若为常规无明显倾向的新闻或符合预期的例行公告，情绪为"中性"，得分为 0.0。
5. 【研报价值评级 (research_value, 1-5星)】：
   - 5星：重大会议/央行货币政策转向、全球硬科技/AI颠覆性突破、重大突发地缘事件。
   - 4星：行业重磅政策、头部公司财报显著超/低于预期、百亿级重大产业并购。
   - 3星：常规行业政策动态、重点个股业绩公告、盘中大类资产显著波动。
   - 2星：次要公司新闻、常规市场日常点评。
   - 1星：日常噪音、营销广告或低价值快讯。
6. 【市场冲击级别 (impact_rating, 1-5级)】：评估该新闻在 24-48 小时内对相关板块价格或市场情绪的冲击烈度（1为微弱，5为剧烈冲击）。
7. 【事件分类 (event_type)】：只能归类为“宏观政策”、“产业动态”、“公司业绩”、“地缘政治”、“市场流动性”或“其他”。
8. 【所属行业板块 (sector)】：结合新闻内容与已知标签，归类为以下具体行业/板块名称之一：
   - "高股息/红利板块"
   - "低估值/破净/回购板块"
   - "大消费/白酒/零售板块"
   - "硬科技/人工智能"
   - "半导体与芯片"
   - "国内宏观与金融流动性"
   - "海外宏观与地缘政治"
   - "其他板块"

【输出要求】：
必须且只能输出严格的纯 JSON 对象，格式如下：
{
  "core_facts": ["事实1", "事实2"],
  "entities": ["实体1", "实体2"],
  "key_metrics": {"营收": "100亿元", "同比": "+15.2%"},
  "sentiment": "看多",
  "sentiment_score": 0.6,
  "research_value": 4,
  "impact_rating": 3,
  "event_type": "产业动态",
  "sector": "硬科技/人工智能"
}
"""


class ExtractorAgent:
    """
    Extractor Agent：负责将 RawNewsSchema 转换为精炼的 StructuredNewsSchema 卡片
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

        # 4. 修复尾随逗号 (Trailing commas: `,}`)
        clean_text = re.sub(r',\s*\}', '}', clean_text)
        clean_text = re.sub(r',\s*\]', ']', clean_text)

        return clean_text

    def _parse_llm_json_response(self, raw_news: Dict[str, Any], response_text: str) -> StructuredNewsSchema:
        """从 LLM 返回的文本中提取并解析 JSON 对象，包含自动修补与容错策略"""
        try:
            clean_json_str = self._repair_json_string(response_text)
            data = json.loads(clean_json_str)

            # 校验情绪枚举
            sentiment_str = data.get("sentiment", "中性")
            if sentiment_str not in ["看多", "看空", "中性"]:
                sentiment_enum = SentimentType.NEUTRAL
            else:
                sentiment_enum = SentimentType(sentiment_str)

            # 限制打分范围 (研报价值 1-5星, 冲击级别 1-5级, 情绪得分 -1.0 到 +1.0)
            research_val = max(1, min(5, int(data.get("research_value", 2))))
            impact_val = max(1, min(5, int(data.get("impact_rating", 2))))
            sent_score = max(-1.0, min(1.0, float(data.get("sentiment_score", 0.0))))

            # 板块归类解析与智能推断
            raw_sec = raw_news.get("sector", "")
            sector_val = data.get("sector")
            if not sector_val or sector_val == "其他板块":
                tags = raw_news.get("category_tags", [])
                if any(t in tags for t in ["高股息", "红利板块"]) or "高股息" in raw_sec:
                    sector_val = "高股息/红利板块"
                elif any(t in tags for t in ["低估值", "破净板块"]) or "低估值" in raw_sec:
                    sector_val = "低估值/破净/回购板块"
                elif any(t in tags for t in ["大消费", "消费板块"]) or "消费" in raw_sec:
                    sector_val = "大消费/白酒/零售板块"
                elif any(t in tags for t in ["半导体", "芯片", "硬件"]) or "半导体" in raw_sec:
                    sector_val = "半导体与芯片"
                elif any(t in tags for t in ["硬科技", "AI/TMT", "AI前沿", "大模型"]) or "硬科技" in raw_sec:
                    sector_val = "硬科技/人工智能"
                elif any(t in tags for t in ["海外宏观", "地缘政治", "美联储"]) or "海外" in raw_sec:
                    sector_val = "海外宏观与地缘政治"
                elif any(t in tags for t in ["7x24快讯", "A股/宏观", "A股"]) or "宏观" in raw_sec:
                    sector_val = "国内宏观与金融流动性"
                else:
                    sector_val = raw_sec if raw_sec and raw_sec != "其他板块" else "其他板块"

            return StructuredNewsSchema(
                raw_id=raw_news.get("news_id", "unknown_id"),
                source=raw_news.get("source", "未知来源"),
                title=raw_news.get("title"),
                core_facts=data.get("core_facts") or [raw_news.get("content", "")[:100]],
                entities=data.get("entities") or raw_news.get("category_tags", []),
                sentiment=sentiment_enum,
                sentiment_score=sent_score,
                research_value=research_val,
                impact_rating=impact_val,
                event_type=data.get("event_type", "产业动态"),
                sector=sector_val,
                key_metrics=data.get("key_metrics", {}),
                category_tags=raw_news.get("category_tags", [])
            )
        except Exception as e:
            app_logger.error(f"❌ Extractor Agent JSON 解析失败: {e}")
            raise ValueError(f"Extractor Agent JSON 解析失败: {e}")

    def extract(self, raw_news: Dict[str, Any]) -> StructuredNewsSchema:
        """单篇新闻资讯抽取主入口"""
        news_id = raw_news.get("news_id", "unknown")
        content = raw_news.get("content", "")
        title = raw_news.get("title") or ""
        sector_name = raw_news.get("sector", "其他板块")
        
        user_prompt = f"所属板块频道: {sector_name}\n新闻标题: {title}\n新闻正文: {content}\n来源: {raw_news.get('source', '')}\n已知标签: {raw_news.get('category_tags', [])}"

        log_agent_action("ExtractorAgent", "Extracting", f"news_id={news_id}")

        try:
            # 使用带超时与重试保护的方法调用 LLM
            prompt = f"{EXTRACTOR_SYSTEM_PROMPT}\n\n【待分析新闻】:\n{user_prompt}"
            response_text = self.llm_factory.invoke_with_circuit_breaker(self.llm, prompt)
            
            card = self._parse_llm_json_response(raw_news, response_text)
            app_logger.info(f"✅ [Extractor Agent] 成功萃取卡片 (raw_id={news_id}, 研报价值={card.research_value}⭐, 情绪={card.sentiment.value})")
            return card

        except Exception as e:
            app_logger.error(f"❌ [Extractor Agent] 执行异常: {e}")
            raise e

    def extract_batch(self, raw_news_list: List[Dict[str, Any]]) -> List[StructuredNewsSchema]:
        """批量新闻资讯抽取接口 (8月4日新增)"""
        cards = []
        log_agent_action("ExtractorAgent", "BatchExtraction", f"Processing {len(raw_news_list)} items")
        for raw in raw_news_list:
            card = self.extract(raw)
            cards.append(card)
        return cards
