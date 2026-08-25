"""
系统订阅与监控配置 Schema (Config Schema)
匹配 TDD 5.2 规格定义
"""
from datetime import datetime, timezone
from typing import List
from pydantic import BaseModel, Field


class ConfigSubscriptionSchema(BaseModel):
    industries: List[str] = Field(default_factory=lambda: ["半导体", "人工智能"], description="订阅重点行业")
    macro_keywords: List[str] = Field(default_factory=lambda: ["美联储", "央行", "PMI", "关税"], description="订阅宏观事件关键词")
    regions: List[str] = Field(default_factory=lambda: ["国内", "美", "日", "韩"], description="订阅关注地区")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="配置最后更新时间")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
