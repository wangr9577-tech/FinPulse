"""DeepSeek 对强势/中等板块生成一句话点评。失败降级为 "—"，不抛出。"""
from openai import OpenAI

from app.stock_daily.config import settings
from app.stock_daily.models import SectorAnalysis

SYSTEM_PROMPT = (
    "你是A股市场板块分析专家。根据板块行情指标与领涨股，用一句话（不超过60字）点评"
    "该板块今日强势的原因与持续性判断。只输出点评文字，不要输出任何其他内容。"
)


def _client() -> OpenAI:
    return OpenAI(api_key=settings.DEEPSEEK_API_KEY, base_url=settings.DEEPSEEK_BASE_URL)


def comment_sector(board: SectorAnalysis) -> str:
    """生成一句话点评。任何异常/无 Key 返回 "—"。"""
    if not settings.DEEPSEEK_API_KEY:
        return "—"
    user = (
        f"板块名：{board.board_name}\n"
        f"板块类型：{'行业' if board.board_type == 'industry' else '概念'}\n"
        f"评分：{board.score:.1f}\n涨幅：{board.pct_change:.2f}%\n"
        f"资金净流入：{board.net_inflow / 1e8:.1f}亿元\n"
        f"上涨家数：{board.up_count}\n"
        f"领涨股：{'、'.join(board.leader_stocks) or '-'}\n"
        "请用一句话点评该板块今日强势的原因与持续性。"
    )
    try:
        resp = _client().chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            temperature=0.4,
            max_tokens=120,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip() or "—"
    except Exception:
        return "—"
