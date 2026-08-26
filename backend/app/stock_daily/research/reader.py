"""重点研报正文提取 + 逐篇 DeepSeek 观点提取。

优先抓取东财研报详情页（data.eastmoney.com/report/zw_stock.jshtml?infocode=XXX）
的服务器渲染 HTML 正文（免鉴权，可绕过 PDF 直链的 JS 反爬挑战）。PDF 直链返回
EO_Bot_Ssid 脚本挑战、httpx 无法执行 JS，故 PDF 仅作 HTML 无正文时的兜底。
提取到正文后交给 DeepSeek 结构化提取核心观点/亮点/风险/目标价依据。
无正文或 LLM 异常降级为仅元数据观点。
"""
import html
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import httpx
from openai import OpenAI

from app.stock_daily.config import settings
from app.stock_daily.http_client import build_headers
from app.stock_daily.models import ReportInsight, ResearchReport
from app.stock_daily.pdf_parser import download_pdf, parse_with_pypdf

SYSTEM_PROMPT = (
    "你是A股券商研报分析专家。根据研报标题与正文，提取研报的核心观点与目标价。"
    "只输出 JSON，不要输出任何其他文字，JSON 格式：\n"
    "{\"summary\": \"核心观点一句话（不超过40字）\", "
    "\"highlights\": [\"亮点1\", \"亮点2\"], "
    "\"risks\": [\"风险1\"], "
    "\"target_basis\": \"目标价/评级依据（不超过40字）\", "
    "\"target_price\": 25.0}\n"
    "target_price：只取正文明确给出的目标价（元），用数字表示；若正文未给出目标价，输出 null。"
    "禁止根据 EPS/PE 或盈利预测估算目标价。"
)

DETAIL_BASE = "https://data.eastmoney.com/report/zw_stock.jshtml"
DETAIL_REFERER = "https://data.eastmoney.com/report/zw_stock.jshtml"


def _build_llm() -> OpenAI:
    """构建 DeepSeek 客户端（供 _call_llm 使用；测试会 monkeypatch 此函数）。

    显式超时 + 收紧重试：与 analyzer._client 保持一致，避免单条挂起把整批拖死。
    """
    return OpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        timeout=30.0,
        max_retries=1,
    )


def _parse_target_price(value) -> float | None:
    """从 DeepSeek 返回的 target_price 解析正数目标价；无/非法/≤0 返回 None。

    只接受正文明确给出的目标价，禁止估算。数字型直接用；字符串可能带"元"/范围，
    取首个正数（如 "25元" → 25.0）。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    m = re.search(r"\d+(?:\.\d+)?", str(value))
    if not m:
        return None
    try:
        n = float(m.group())
    except ValueError:
        return None
    return n if n > 0 else None


def _as_list(value) -> list[str]:
    """JSON 字段安全转字符串列表；非 list 或元素非 str 时丢弃，避免把字符串拆成字符。"""
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, str)]


def _call_llm(report: ResearchReport, text: str) -> ReportInsight:
    """DeepSeek 提取观点。异常抛出（由 _analyze_report 降级捕获）。"""
    user = (
        f"研报标题：{report.title}\n"
        f"机构：{report.org_name} ｜ 研究员：{report.researcher}\n"
        f"评级：{report.rating} ｜ 目标价：{report.aim_price_t or '-'}\n"
        f"研报正文（摘要）：\n{text}"
    )
    resp = _build_llm().chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=500,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    )
    raw = resp.choices[0].message.content or ""
    try:
        obj = json.loads(raw)
    except Exception as exc:
        raise ValueError(f"研报观点 JSON 解析失败: {raw[:80]!r}") from exc
    if not isinstance(obj, dict):
        raise ValueError("研报观点 JSON 非对象")
    return ReportInsight(
        report=report,
        summary=str(obj.get("summary") or "").strip(),
        highlights=_as_list(obj.get("highlights")),
        risks=_as_list(obj.get("risks")),
        target_basis=str(obj.get("target_basis") or "").strip(),
        target_price=_parse_target_price(obj.get("target_price")),
    )


def _meta_insight(report: ResearchReport) -> ReportInsight:
    """仅元数据降级观点：用标题 + 评级拼一句话（无正文/解析失败/LLM 异常时）。"""
    return ReportInsight(
        report=report,
        summary=f"仅标题与元数据：{report.title}（评级 {report.rating or '-'}）",
        degraded=True,
    )


def _extract_body_text(html_text: str) -> str:
    """从 zw_stock.jshtml 详情页提取 ctx-content 正文（<p> 段落 → 纯文本）。

    报告正文位于 <div id="ctx-content" class="ctx-content"> 内，由多个 <p> 段落组成。
    非贪婪取到第一个 </div> 即闭合容器；随后剥离标签、unescape HTML 实体、
    去首尾空白、压缩连续空白，并截断到 settings.PDF_TEXT_CHARS。
    """
    m = re.search(r'<div\s+id="ctx-content"[^>]*>(.*?)</div>', html_text, re.S)
    seg = m.group(1) if m else html_text
    seg = re.sub(r'<script.*?</script>', " ", seg, flags=re.S)
    seg = re.sub(r'<style.*?</style>', " ", seg, flags=re.S)
    seg = re.sub(r'<br\s*/?>', "\n", seg)
    seg = re.sub(r'</p>', "\n", seg)
    seg = re.sub(r'<[^>]+>', " ", seg)
    seg = html.unescape(seg)
    seg = seg.replace("　", " ")  # 全角空格 → 半角，便于压缩
    lines = [re.sub(r"\s+", " ", l).strip() for l in seg.split("\n")]
    body = "\n".join(l for l in lines if l)
    return body[: settings.PDF_TEXT_CHARS]


def _fetch_html_text(report: ResearchReport, client: httpx.Client) -> str:
    """抓详情页 HTML 并提取正文。无 info_code / 请求失败 / 无正文返回 ""。"""
    if not report.info_code:
        return ""
    try:
        resp = client.get(
            f"{DETAIL_BASE}?infocode={report.info_code}",
            headers=build_headers(DETAIL_REFERER),
            timeout=30,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return ""
        return _extract_body_text(resp.text)
    except Exception:
        return ""


def _analyze_report(report: ResearchReport, html_text: str, pdf_path: Path | None) -> ReportInsight:
    """单篇研报：正文（HTML 优先，PDF 兜底）→ DeepSeek 观点。无正文/LLM 异常降级。"""
    if not settings.DEEPSEEK_API_KEY:
        return _meta_insight(report)
    pdf_text = parse_with_pypdf(pdf_path, settings.PDF_TEXT_CHARS) if pdf_path else ""
    body = html_text if len(html_text) >= settings.PDF_MIN_CHARS else pdf_text
    if not body:
        return _meta_insight(report)
    try:
        return _call_llm(report, body)
    except Exception:
        return _meta_insight(report)


def _pdf_key(r: ResearchReport) -> str:
    """同股多研报区分键：代码|标题。3 日回看内一只股票常有数篇研报，
    仅按代码归档会把多篇研报的正文张冠李戴到最后一篇下载成功的 PDF 上。"""
    return f"{r.stock_code}|{r.title}"


def _safe_key(key: str) -> str:
    """Windows 文件系统安全名：非法字符与控制字符替换、截断、去首尾空白。"""
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", key)
    return safe[:80].strip(" .") or "_"


def extract_insights(
    reports: list[ResearchReport],
    ann_date: str | date,
    logger: logging.Logger | None,
) -> list[ReportInsight]:
    """并发抓取正文（HTML 优先，PDF 兜底）+ 提取观点。

    单篇失败降级，不阻断整批；按输入顺序返回。
    """
    if not reports:
        return []
    pdf_dir = settings.RESEARCH_PDF_DIR / str(ann_date)

    # 阶段1：HTML 详情页正文（免 PDF 下载，主路径）
    html_map: dict[str, str] = {}
    with httpx.Client(timeout=30) as client, ThreadPoolExecutor(
        max_workers=settings.DOWNLOAD_CONCURRENCY
    ) as ex:
        futures = {
            ex.submit(_fetch_html_text, r, client): _pdf_key(r)
            for r in reports if r.info_code
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                t = fut.result()
                if t and len(t) >= settings.PDF_MIN_CHARS:
                    html_map[key] = t
            except Exception:
                continue

    # 阶段2：HTML 无正文的再看 PDF 直链（兜底）
    pdf_map: dict[str, Path] = {}
    need_pdf = [_pdf_key(r) for r in reports if _pdf_key(r) not in html_map and r.pdf_url]
    if need_pdf:
        with httpx.Client(timeout=60) as client, ThreadPoolExecutor(
            max_workers=settings.DOWNLOAD_CONCURRENCY
        ) as ex:
            futures = {
                ex.submit(
                    download_pdf, r.pdf_url, pdf_dir / _safe_key(_pdf_key(r)), client
                ): _pdf_key(r)
                for r in reports if _pdf_key(r) not in html_map and r.pdf_url
            }
            for fut in as_completed(futures):
                key = futures[fut]
                try:
                    p = fut.result()
                    if p:
                        pdf_map[key] = p
                except Exception:
                    continue

    if logger:
        logger.info(f"研报正文来源：HTML {len(html_map)} 篇 + PDF {len(pdf_map)} 篇")

    # 阶段3：逐篇观点提取
    results: dict[str, ReportInsight] = {}
    with ThreadPoolExecutor(max_workers=settings.RESEARCH_CONCURRENCY) as ex:
        futures = {
            ex.submit(_analyze_report, r, html_map.get(_pdf_key(r)), pdf_map.get(_pdf_key(r))): _pdf_key(r)
            for r in reports
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                results[key] = fut.result()
            except Exception:
                continue
    insights = [results[_pdf_key(r)] for r in reports if _pdf_key(r) in results]
    degraded_count = sum(1 for i in insights if i.degraded)
    if logger:
        logger.info(f"研报观点提取完成 {len(insights)} 篇（降级 {degraded_count} 篇）")
    return insights
