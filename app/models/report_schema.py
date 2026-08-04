"""
研报与分析报告数据模型 (Report Schema)
匹配 TDD 5.1 / 6.0 规格定义
"""
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field


class MacroAlertSchema(BaseModel):
    is_triggered: bool = Field(False, description="是否触发宏观预警")
    events: List[str] = Field(default_factory=list, description="触发预警的宏观事件清单")


class MarketInsightReportSchema(BaseModel):
    report_id: str = Field(..., description="研报唯一标识 (例: rep_20260727_01)")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="生成时间")
    target_industries: List[str] = Field(default_factory=list, description="关注的目标行业 (如 半导体, 人工智能)")
    macro_alert: MacroAlertSchema = Field(default_factory=MacroAlertSchema, description="宏观预警信息")
    content_markdown: str = Field(..., description="Markdown 格式生成的综合研报正文")
    charts_data: Dict[str, Any] = Field(default_factory=dict, description="关联图表及指标算子数据 (如两融占比等)")
    generation_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="存储/归档时间")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
