"""选股综合：排序取前 3-5 支 + DeepSeek 融合推荐理由。

无 DeepSeek key → 纯分数排序，reason 用规则拼接（降级契约）。
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from openai import OpenAI

from app.stock_daily.config import settings
from app.stock_daily.models import StockCandidate, StockPick, StockPicks

SYSTEM_PROMPT = (
    "你是A股选股推荐专家。基于候选股的综合评分与依据，为每支股票写一段"
    "不超过60字的推荐理由（说明公告利好点 + 研报观点 + 风险提示）。"
    "只输出 JSON 对象，不要输出其他文字，格式：\n"
    "{\"picks\": [{\"code\": \"300693\", \"reason\": \"...\", \"risk_note\": \"...\"}]}"
)


def _client() -> OpenAI:
    return OpenAI(api_key=settings.DEEPSEEK_API_KEY, base_url=settings.DEEPSEEK_BASE_URL)


def _rule_reason(c: StockCandidate) -> tuple[str, str]:
    """无 LLM 时的规则理由：(reason, risk_note)。"""
    parts = []
    if c.ann_level:
        parts.append(f"公告利好({c.ann_level})")
    if c.rating:
        parts.append(f"研报评级({c.rating})")
    if c.target_upside > 0:
        parts.append(f"目标价空间{c.target_upside:.1f}%")
    reason = "、".join(parts) + f"，综合评分{c.score:.1f}" if parts else f"综合评分{c.score:.1f}"
    return reason, "仅供研究参考，不构成投资建议"


def _llm_reason(c: StockCandidate, ann_brief: str, research_brief: str) -> tuple[str, str]:
    """DeepSeek 生成推荐理由 + 风险提示。异常回退规则理由。"""
    user = (
        f"股票：{c.stock_code} {c.stock_name}\n"
        f"综合评分：{c.score:.1f}\n公告利好程度：{c.ann_level or '无'}\n"
        f"研报评级：{c.rating or '无'}\n目标价空间：{c.target_upside:.1f}%\n"
        f"公告利好点：{ann_brief or '-'}\n研报观点：{research_brief or '-'}\n"
        "请给出推荐理由与风险提示。"
    )
    try:
        resp = _client().chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=400,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        )
        raw = resp.choices[0].message.content or ""
        obj = json.loads(raw)
        items = (obj or {}).get("picks") or []
        if not isinstance(items, list):
            items = [items]
        for it in items:
            if str(it.get("code")) == c.stock_code:
                reason = str(it.get("reason") or "").strip()
                if not reason:
                    return _rule_reason(c)
                risk = str(it.get("risk_note") or "").strip()
                return reason, risk or _rule_reason(c)[1]
    except Exception:
        pass
    return _rule_reason(c)


def _pick_one(
    c: StockCandidate,
    ann_brief_map: dict[str, str],
    research_brief_map: dict[str, str],
    ann_links_map: dict[str, list[str]] | None = None,
    reports_map: dict[str, list] | None = None,
) -> StockPick:
    if settings.DEEPSEEK_API_KEY:
        reason, risk = _llm_reason(c, ann_brief_map.get(c.stock_code, ""),
                                   research_brief_map.get(c.stock_code, ""))
    else:
        reason, risk = _rule_reason(c)
    return StockPick(
        stock_code=c.stock_code, stock_name=c.stock_name,
        reason=reason, ann_brief=ann_brief_map.get(c.stock_code, ""),
        research_brief=research_brief_map.get(c.stock_code, ""),
        target_upside=c.target_upside, risk_note=risk,
        ann_links=(ann_links_map or {}).get(c.stock_code, []),
        reports=(reports_map or {}).get(c.stock_code, []),
    )


def build_picks(
    candidates: list[StockCandidate],
    report_date: str | date,
    ann_brief_map: dict[str, str] | None = None,
    research_brief_map: dict[str, str] | None = None,
    ann_links_map: dict[str, list[str]] | None = None,
    reports_map: dict[str, list] | None = None,
) -> StockPicks:
    """取前 PICK_MAX 支（不足 PICK_MIN 不硬凑）生成推荐。"""
    ann_brief_map = ann_brief_map or {}
    research_brief_map = research_brief_map or {}
    ann_links_map = ann_links_map or {}
    reports_map = reports_map or {}
    cands = sorted(candidates, key=lambda c: c.score, reverse=True)[:settings.PICK_MAX]
    picks: list[StockPick] = []
    if cands and settings.DEEPSEEK_API_KEY:
        with ThreadPoolExecutor(max_workers=settings.RESEARCH_CONCURRENCY) as ex:
            futures = {ex.submit(_pick_one, c, ann_brief_map, research_brief_map,
                                 ann_links_map, reports_map): c for c in cands}
            for fut in as_completed(futures):
                try:
                    picks.append(fut.result())
                except Exception:
                    pass
    elif cands:
        picks = [_pick_one(c, ann_brief_map, research_brief_map,
                           ann_links_map, reports_map) for c in cands]
    score_order = {c.stock_code: c.score for c in cands}
    picks.sort(key=lambda p: -score_order.get(p.stock_code, 0))
    note = ""
    if not candidates:
        note = "今日无符合条件个股（无重点研报或无有效评分）"
    return StockPicks(date=date.fromisoformat(str(report_date)) if not isinstance(report_date, date) else report_date,
                      picks=picks, note=note)
