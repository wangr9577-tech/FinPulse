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
你的任务是从给定的原始财经新闻/快讯文本中，提炼高密度的结构化情报卡片。

请严格遵守以下萃取与打分规则：
1. 【核心事实 (core_facts)】：从文本中提取 1~3 条最关键的客观事实陈述，要求简明扼要，拒绝冗余废话。
2. 【实体识别 (entities)】：提取新闻中涉及的所有核心实体（公司股票、产业名称、政府机构、关键产品或人物）。
3. 【情绪与得分 (sentiment & sentiment_score)】：
   - 情绪分类：看多 / 看空 / 中性。
   - 情绪得分：-1.0 (极度利空) 到 +1.0 (极度利多) 之间的浮点数。
4. 【研报价值评级 (research_value, 1-5星)】：
   - 5 星：央行重大货币政策改变、地缘重大突发、全球硬科技/AI颠覆性突破（极其具备研报深读价值）。
   - 4 星：行业重磅政策、头部公司核心财报超预期、大额产业并购。
   - 3 星：常规行业动态、重点个股公告、大类资产盘中显著波动。
   - 2 星：常规市场点评、次要公司新闻。
   - 1 星：日常新闻噪音或低价值快讯。
5. 【市场冲击级别 (impact_rating, 1-5级)】：评估该新闻在 24-48 小时内对市场相关板块价格或情绪的冲击烈度（1为微弱，5为剧烈冲击）。
6. 【事件分类 (event_type)】：归类为“宏观政策”、“产业动态”、“公司业绩”、“地缘政治”、“市场流动性”或“其他”。

请确保输出为合法的 JSON 格式，字段名如下：
{
  "core_facts": ["事实1", "事实2"],
  "entities": ["实体1", "实体2"],
  "sentiment": "看多/看空/中性",
  "sentiment_score": 0.5,
  "research_value": 4,
  "impact_rating": 3,
  "event_type": "产业动态",
  "key_metrics": {"利息": "1.5%", "金额": "2000亿"}
}
"""


class ExtractorAgent:
    """
    Extractor Agent：负责将 RawNewsSchema 转换为精炼的 StructuredNewsSchema 卡片
    """
    def __init__(self, llm_factory: Optional[LLMFactory] = None, model_tier: str = "flash"):
        self.llm_factory = llm_factory or LLMFactory(request_timeout=30.0, max_retries=3)
        self.model_tier = model_tier.lower()
        if self.model_tier == "pro":
            self.llm = self.llm_factory.get_pro_llm()
        else:
            self.llm = self.llm_factory.get_flash_llm()

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
                sector=raw_news.get("sector", "其他板块"),
                key_metrics=data.get("key_metrics", {}),
                category_tags=raw_news.get("category_tags", [])
            )
        except Exception as e:
            app_logger.warning(f"⚠️ Extractor Agent JSON 解析容错机制触发 ({e}): 启动规则降级生成卡片")
            return self._fallback_extract(raw_news)

    def _fallback_extract(self, raw_news: Dict[str, Any]) -> StructuredNewsSchema:
        """无 Key 或解析异常时的硬规则降级抽取器"""
        title = raw_news.get("title") or ""
        content = raw_news.get("content", "")
        text = f"{title} {content}"

        # 简单规则计算研报价值 rating
        importance = raw_news.get("importance", 1)
        research_val = min(5, importance + (1 if len(content) > 100 else 0))
        
        # 简单敏感词识别情绪
        if any(w in text for w in ["大增", "突破", "降息", "净流入", "利好"]):
            sentiment = SentimentType.BULLISH
            score = 0.6
        elif any(w in text for w in ["大跌", "制裁", "关税", "爆雷", "利空"]):
            sentiment = SentimentType.BEARISH
            score = -0.6
        else:
            sentiment = SentimentType.NEUTRAL
            score = 0.0

        return StructuredNewsSchema(
            raw_id=raw_news.get("news_id", "fallback_id"),
            source=raw_news.get("source", "快讯源"),
            title=raw_news.get("title"),
            core_facts=[content[:120] + ("..." if len(content) > 120 else "")],
            entities=raw_news.get("category_tags", []),
            sentiment=sentiment,
            sentiment_score=score,
            research_value=research_val,
            impact_rating=importance,
            event_type="产业动态",
            sector=raw_news.get("sector", "其他板块"),
            key_metrics={},
            category_tags=raw_news.get("category_tags", [])
        )

    def extract(self, raw_news: Dict[str, Any]) -> StructuredNewsSchema:
        """单篇新闻资讯抽取主入口"""
        news_id = raw_news.get("news_id", "unknown")
        content = raw_news.get("content", "")
        title = raw_news.get("title") or ""
        sector_name = raw_news.get("sector", "其他板块")
        
        user_prompt = f"所属板块频道: {sector_name}\n新闻标题: {title}\n新闻正文: {content}\n来源: {raw_news.get('source', '')}\n已知标签: {raw_news.get('category_tags', [])}"

        log_agent_action("ExtractorAgent", "Extracting", f"news_id={news_id}, model_tier={self.model_tier}")

        try:
            # 使用带超时与重试保护的方法调用 LLM
            prompt = f"{EXTRACTOR_SYSTEM_PROMPT}\n\n【待分析新闻】:\n{user_prompt}"
            response_text = self.llm_factory.invoke_with_circuit_breaker(self.llm, prompt)
            
            card = self._parse_llm_json_response(raw_news, response_text)
            app_logger.info(f"✅ [Extractor Agent] 成功萃取卡片 (raw_id={news_id}, 研报价值={card.research_value}⭐, 情绪={card.sentiment.value})")
            return card

        except Exception as e:
            app_logger.error(f"❌ [Extractor Agent] 执行异常: {e}，切入兜底规则。")
            return self._fallback_extract(raw_news)

    def extract_batch(self, raw_news_list: List[Dict[str, Any]]) -> List[StructuredNewsSchema]:
        """批量新闻资讯抽取接口 (8月4日新增)"""
        cards = []
        log_agent_action("ExtractorAgent", "BatchExtraction", f"Processing {len(raw_news_list)} items")
        for raw in raw_news_list:
            card = self.extract(raw)
            cards.append(card)
        return cards
