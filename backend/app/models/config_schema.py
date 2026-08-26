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
    report_sectors: List[str] = Field(
        default_factory=lambda: ["国内宏观", "国外宏观", "半导体", "互联网服务", "银行"],
        description="研报默认包含板块 (资讯研报仅分析/渲染这些板块)",
    )
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="配置最后更新时间")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class DailyAutoRunSchema(BaseModel):
    """每日自动运行开关：控制后端定时任务是否在 run_time 每天跑一遍全部内容。"""
    enabled: bool = Field(default=False, description="是否启用每日自动运行")
    run_time: str = Field(default="07:00", description="每日自动运行时间 (HH:MM)")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="配置最后更新时间")


class ReportEmailSchema(BaseModel):
    """邮件接收配置：跑完后把产出的报告通过邮箱发送到指定邮箱。"""
    enabled: bool = Field(default=False, description="是否启用邮件发送")
    recipients: List[str] = Field(default_factory=list, description="收件人邮箱列表")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="配置最后更新时间")
