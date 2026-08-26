"""重点研报 PDF 下载 + 逐篇 DeepSeek 观点提取。

每篇重点研报（买入/增持）下载 PDF → pypdf 提取正文 → DeepSeek 结构化提取
核心观点/亮点/风险/目标价依据。PDF 解析失败或 LLM 异常降级为仅元数据观点。
"""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import httpx
from openai import OpenAI

from app.stock_daily.config import settings
from app.stock_daily.models import ReportInsight, ResearchReport
from app.stock_daily.pdf_parser import download_pdf, parse_with_pypdf

SYSTEM_PROMPT = (
    "你是A股券商研报分析专家。根据研报标题与正文，提取研报的核心观点。"
    "只输出 JSON，不要输出任何其他文字，JSON 格式：\n"
    "{\"summary\": \"核心观点一句话（不超过40字）\", "
    "\"highlights\": [\"亮点1\", \"亮点2\"], "
    "\"risks\": [\"风险1\"], "
    "\"target_basis\": \"目标价/评级依据（不超过40字）\"}\n"
)


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


def _as_list(value) -> list[str]:
    """JSON 字段安全转字符串列表；非 list 或元素非 str 时丢弃，避免把字符串拆成字符。"""
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, str)]


def _call_llm(report: ResearchReport, text: str) -> ReportInsight:
    """DeepSeek 提取观点。异常抛出（由 analyze_report 降级捕获）。"""
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
    )


def _meta_insight(report: ResearchReport) -> ReportInsight:
    """仅元数据降级观点：用标题 + 评级拼一句话（PDF 解析失败/LLM 异常时）。"""
    return ReportInsight(
        report=report,
        summary=f"仅标题与元数据：{report.title}（评级 {report.rating or '-'}）",
        degraded=True,
    )


def analyze_report(report: ResearchReport, pdf_path: Path | None) -> ReportInsight:
    """单篇研报：PDF 正文 → DeepSeek 观点。无 PDF/解析失败/LLM 异常均降级。"""
    if not settings.DEEPSEEK_API_KEY:
        return _meta_insight(report)
    if pdf_path is None:
        return _meta_insight(report)
    text = parse_with_pypdf(pdf_path, settings.PDF_TEXT_CHARS)
    if not text:
        return _meta_insight(report)
    try:
        return _call_llm(report, text)
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
    """并发下载 PDF + 提取观点。单篇失败降级，不阻断整批；按输入顺序返回。"""
    if not reports:
        return []
    pdf_dir = settings.RESEARCH_PDF_DIR / str(ann_date)
    with httpx.Client(timeout=60) as client, ThreadPoolExecutor(
        max_workers=settings.DOWNLOAD_CONCURRENCY
    ) as ex:
        futures = {
            ex.submit(download_pdf, r.pdf_url, pdf_dir / _safe_key(_pdf_key(r)), client): _pdf_key(r)
            for r in reports if r.pdf_url
        }
        pdf_map: dict[str, Path] = {}
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                p = fut.result()
                if p:
                    pdf_map[key] = p
            except Exception:
                continue
    if logger:
        logger.info(f"研报 PDF 下载完成 {len(pdf_map)} 篇")

    results: dict[str, ReportInsight] = {}
    with ThreadPoolExecutor(max_workers=settings.RESEARCH_CONCURRENCY) as ex:
        futures = {
            ex.submit(analyze_report, r, pdf_map.get(_pdf_key(r))): _pdf_key(r)
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
