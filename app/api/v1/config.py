"""
系统订阅与监控偏好设置接口 (Config Subscriptions Endpoint)
匹配 TDD 5.2 协议规范: POST /api/v1/config/subscriptions
"""
from fastapi import APIRouter
from app.models.config_schema import ConfigSubscriptionSchema
from app.db.mongodb import MongoDBClient

router = APIRouter(prefix="/config", tags=["Configuration"])


@router.get("/subscriptions", summary="获取当前用户/系统订阅配置")
async def get_subscriptions():
    db_client = MongoDBClient.get_instance()
    cfg = await db_client.get_system_config()
    return {
        "code": 200,
        "message": "success",
        "data": cfg
    }


@router.post("/subscriptions", summary="更新系统监控与抓取订阅配置")
async def update_subscriptions(subscription_req: ConfigSubscriptionSchema):
    db_client = MongoDBClient.get_instance()
    updated_cfg = await db_client.update_system_config(subscription_req.model_dump())
    return {
        "code": 200,
        "message": "订阅配置更新成功",
        "data": updated_cfg
    }
