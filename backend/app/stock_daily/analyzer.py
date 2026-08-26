"""DeepSeek 影响分析（OpenAI 兼容接口）。

模型返回必须为 JSON（response_format=json_object）；解析失败时降级为中性/低。
"""
import json
import re

from openai import OpenAI

from app.stock_daily.config import settings
from app.stock_daily.models import AnalysisResult, Announcement

SYSTEM_PROMPT = (
    "你是A股上市公司公告的专业分析师。根据公告内容判断其对该公司股价的影响。"
    "只输出 JSON，不要输出任何其他文字。JSON 必须包含以下字段：\n"
    "{\"sentiment\": \"利好|利空|中性\", \"level\": \"高|中|低\", "
    "\"sectors\": [\"关联板块\"], \"reason\": \"一句话理由（不超过50字）\", "
    "\"key_points\": [\"要点1\", \"要点2\"]}\n"
    "sentiment 必须是 利好/利空/中性 之一；level 必须是 高/中/低 之一。"
)

TITLE_SYSTEM_PROMPT = (
    "你是A股上市公司公告的专业分析师。仅根据公告标题（与公告类型）判断其对公司股价的短期影响，"
    "不要假设正文内容。只输出 JSON，不要输出任何其他文字，JSON 格式：\n"
    "{\"sentiment\": \"利好|中性|利空\", \"level\": \"高|中|低\", \"reason\": \"一句话理由（不超过30字）\"}\n"
    "规则：\n"
    "- 利好：标题本身明确传递正面信号（如业绩预增、中标、增持、回购、重组获批等），level 表示利好程度。\n"
    "- 利空：标题本身明确传递负面信号（如减持、诉讼、处罚、亏损、事故、停产等）。\n"
    "- 中性：标题无明显利好或利空信号（如例行披露、定期报告、常规事项等）。\n"
)

_DEGRADED = AnalysisResult(sentiment="中性", level="低", degraded=True)


def _build_user_prompt(ann: Announcement) -> str:
    text = (
        f"公司代码：{ann.stock_code}\n"
        f"公司名称：{ann.stock_name}\n"
        f"公告标题：{ann.title}\n"
        f"公告类型：{ann.category}\n"
    )
    if ann.full_text:
        text += f"公告正文（摘要）：\n{ann.full_text}"
    else:
        text += "（该公告无正文，请基于标题谨慎判断）"
    return text


def _build_title_user_prompt(ann: Announcement) -> str:
    return (
        f"公司代码：{ann.stock_code}\n"
        f"公司名称：{ann.stock_name}\n"
        f"公告标题：{ann.title}\n"
        f"公告类型：{ann.category}\n"
    )


def _client() -> OpenAI:
    # 显式超时 + 收紧重试：单次挂起请求在 ~30s 内降级为中性/低，不再让 8 个并发
    # 线程被无响应请求硬阻塞（SDK 默认 600s 超时 + 2 次重试会把整段拖死 30 分钟以上）。
    return OpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        timeout=30.0,
        max_retries=1,
    )


def analyze_one(ann: Announcement) -> AnalysisResult:
    """分析单条公告。任何异常/无 Key 都降级返回，不抛出。"""
    if not settings.DEEPSEEK_API_KEY:
        return _DEGRADED.model_copy(deep=True)
    try:
        resp = _client().chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=500,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(ann)},
            ],
        )
        raw = resp.choices[0].message.content
        return _parse_json(raw, full_text_analyzed=bool(ann.full_text))
    except Exception:
        return _DEGRADED.model_copy(deep=True)


def judge_by_title(ann: Announcement) -> AnalysisResult:
    """仅读标题判定情绪（利好/中性/利空 + 利好程度）。任何异常降级为中性，不抛出。"""
    if not settings.DEEPSEEK_API_KEY:
        return _DEGRADED.model_copy(deep=True)
    try:
        resp = _client().chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=200,
            messages=[
                {"role": "system", "content": TITLE_SYSTEM_PROMPT},
                {"role": "user", "content": _build_title_user_prompt(ann)},
            ],
        )
        raw = resp.choices[0].message.content
        return _parse_json(raw, full_text_analyzed=False)
    except Exception:
        return _DEGRADED.model_copy(deep=True)


def _parse_json(raw: str | None, full_text_analyzed: bool) -> AnalysisResult:
    obj: dict = {}
    if raw:
        try:
            obj = json.loads(raw)
        except Exception:
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                try:
                    obj = json.loads(m.group(0))
                except Exception:
                    obj = {}
    sentiment = obj.get("sentiment", "中性")
    if sentiment not in ("利好", "利空", "中性"):
        sentiment = "中性"
    level = obj.get("level", "低")
    if level not in ("高", "中", "低"):
        level = "低"
    return AnalysisResult(
        sentiment=sentiment,
        level=level,
        sectors=list(obj.get("sectors") or []),
        reason=str(obj.get("reason") or "").strip(),
        key_points=list(obj.get("key_points") or []),
        full_text_analyzed=full_text_analyzed,
        degraded=not full_text_analyzed,
    )
