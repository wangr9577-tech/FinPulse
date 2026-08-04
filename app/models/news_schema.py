"""
新闻与资讯数据 Schema 定义
包含 RawNewsSchema (原始抓取) 与 StructuredNewsSchema (Extractor Agent 提取精炼卡片)
"""
from enum import Enum
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class SentimentType(str, Enum):
    """情绪判定枚举"""
    BULLISH = "看多"
    BEARISH = "看空"
    NEUTRAL = "中性"


class EventType(str, Enum):
    """事件分类类型"""
    MACRO_POLICY = "宏观政策"
    INDUSTRY_TREND = "产业动态"
    COMPANY_EARNINGS = "公司业绩"
    GEOPOLITICS = "地缘政治"
    MARKET_LIQUIDITY = "市场流动性"
    OTHER = "其他"


class RawNewsSchema(BaseModel):
    """
    第一层/源头抓取的原始新闻资讯标准数据结构
    """
    news_id: str = Field(..., description="按存入/抓取数量严格递增的唯一新闻ID，格式为: news_{序号} (例: news_1, news_2)")
    source: str = Field(..., description="新闻来源名称 (例: 财联社, 华尔街见闻, 东方财富)")
    title: Optional[str] = Field(None, description="新闻标题 (快讯类若无标题则为 None)")
    content: str = Field(..., description="新闻正文/摘要纯文本")
    publish_time: datetime = Field(..., description="原始发布时间 (带时区或 UTC)")
    crawled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="系统抓取入库时间")
    category_tags: List[str] = Field(default_factory=list, description="相关板块/标签 (如 A股, 宏观, 央行)")
    importance: int = Field(1, description="重要程度评级 (1: 常规, 2: 重点关注, 3: 紧急爆红)")
    channel_type: str = Field("json_api", description="获取通道: json_api / rsshub / playwright / rss_channel")
    raw_payload: Dict[str, Any] = Field(default_factory=dict, description="原始 JSON / XML 结构备份")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class StructuredNewsSchema(BaseModel):
    """
    第二层 (Extractor Agent) 提取生成的精炼情报卡片模型
    满足 8月3日 WBS 细化子任务规范
    """
    raw_id: str = Field(..., description="关联 raw_news_collection 的 news_id")
    source: str = Field(..., description="新闻来源名称")
    title: Optional[str] = Field(None, description="新闻标题")
    core_facts: List[str] = Field(default_factory=list, description="LLM 提取的核心事实列表 (条理清晰简明扼要)")
    entities: List[str] = Field(default_factory=list, description="提取的关键实体 (公司/机构/产业/产品)")
    sentiment: SentimentType = Field(SentimentType.NEUTRAL, description="情绪倾向: 看多 / 看空 / 中性")
    sentiment_score: float = Field(0.0, description="情绪偏向得分 (-1.0 极度看空 至 +1.0 极度看多)")
    research_value: int = Field(1, ge=1, le=5, description="研报价值评级 (1-5 星打分，5 为最具投研深读价值)")
    impact_rating: int = Field(1, ge=1, le=5, description="市场冲击级别 (1-5 级，5 为重大宏观/地缘冲击)")
    event_type: str = Field("产业动态", description="事件分类类型 (如 宏观政策, 产业动态, 公司业绩等)")
    key_metrics: Dict[str, Any] = Field(default_factory=dict, description="提取的关键量化指标 (如 利率变化, 投资金额)")
    category_tags: List[str] = Field(default_factory=list, description="分类打标")
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Extractor 萃取完成入库时间")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
