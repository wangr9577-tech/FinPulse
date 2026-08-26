"""
每日投资日报渲染 (app/stock_daily/report_render.py)
========================================================================
把 daily_stock_reports 集合里的 data (DailyReportData.model_dump(mode="json") 字典)
渲染成买方研报风格的 Markdown，再交 scripts.convert_report_to_pdf.compile_report_to_pdf
导出为 PDF 附件。

设计约束（《前端/邮件接入规范》）：
  - 只渲染真实字段。字段缺失 / None / 空列表一律显示 "-" 或「暂无」，绝不编造数据。
  - 日期、金额、百分比用辅助函数格式化；金额以「亿/万」为单位就近显示。
"""

from typing import Any, Dict, List, Optional


def _fmt(v: Any, default: str = "-") -> str:
    """安全字符串化：None / 空串 / 非有限数值 → default，其余转为去尾零字符串。"""
    if v is None:
        return default
    if isinstance(v, float):
        # 去除浮点尾巴 (如 70.0 -> 70, 63.4 -> 63.4)
        return f"{v:g}"
    s = str(v).strip()
    return s if s else default


def _fmt_amount(v: Any) -> str:
    """资金净流入/流通市值：按亿/万就近显示，None 或非法 → '-'."""
    if v is None:
        return "-"
    try:
        num = float(v)
    except (TypeError, ValueError):
        return "-"
    if abs(num) >= 1e8:
        return f"{num / 1e8:.2f}亿"
    if abs(num) >= 1e4:
        return f"{num / 1e4:.2f}万"
    return f"{num:.0f}"


def _fmt_pct(v: Any, default: str = "-") -> str:
    """百分比：带正负号，保留两位，None → '-'."""
    if v is None:
        return default
    try:
        num = float(v)
    except (TypeError, ValueError):
        return default
    sign = "+" if num > 0 else ""
    return f"{sign}{num:.2f}%"


def render_daily_report_markdown(data: Dict[str, Any]) -> str:
    """把 DailyReportData JSON 字典转成 Markdown 字符串。

    入参 data 即 daily_stock_reports 的 data 字段（model_dump(mode="json") 后的字典）。
    data 为空 / None 时返回占位说明 Markdown。
    """
    if not data:
        return "# 每日投资日报\n\n> 今日暂无数据（未运行或数据源不可达）。"

    date_str = _fmt(data.get("date"), "未知日期")
    anns = data.get("announcements") or {}
    sectors_strong = data.get("sectors_strong") or []
    sectors_medium = data.get("sectors_medium") or []
    stock_picks = data.get("stock_picks") or {}
    forecasts = data.get("forecasts") or []

    # ---------- 头部 ----------
    lines = [f"# {date_str} 每日投资日报", ""]

    # ---------- KPI ----------
    ann_total = anns.get("total", 0)
    pick_list = stock_picks.get("picks") or []
    kpi = [
        ("利好公告", _fmt(ann_total)),
        ("强势板块", _fmt(len(sectors_strong))),
        ("中等板块", _fmt(len(sectors_medium))),
        ("业绩预告", _fmt(len(forecasts))),
        ("选股数", _fmt(len(pick_list))),
    ]
    lines.append("## 一、今日概览")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("| :--- | :--- |")
    for name, val in kpi:
        lines.append(f"| {name} | {val} |")
    lines.append("")

    sources_note = anns.get("sources_note", "")
    if sources_note:
        lines.append(f"> 提示：{sources_note}")
        lines.append("")

    # ---------- 每日选股推荐 ----------
    lines.append("## 二、每日选股推荐")
    lines.append("")
    pick_note = stock_picks.get("note", "") or ""
    if pick_list:
        lines.append("| 代码 | 简称 | 目标涨幅 | 推荐理由 |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for p in pick_list:
            lines.append(
                f"| {_fmt(p.get('stock_code'))} | {_fmt(p.get('stock_name'))} | "
                f"{_fmt_pct(p.get('target_upside'))} | {_fmt(p.get('reason'))} |"
            )
    elif pick_note:
        lines.append(f"{pick_note}")
    else:
        lines.append("（今日无选股推荐）")
    lines.append("")

    # ---------- 强势 / 中等板块 ----------
    def _sector_block(title: str, boards: List[Dict[str, Any]]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        if not boards:
            lines.append("（今日暂无）")
            lines.append("")
            return
        for b in boards:
            leader = "、".join(b.get("leader_stocks") or []) or "-"
            lines.append(
                f"### {_fmt(b.get('board_name'))}（{_fmt(b.get('grade'))}）"
                f"{_fmt_pct(b.get('pct_change'))}"
            )
            lines.append("")
            lines.append(
                f"- **评分**：{_fmt(b.get('score'))}"
                f"　**资金净流入**：{_fmt_amount(b.get('net_inflow'))}"
                f"　**领涨股**：{leader}"
            )
            research_note = b.get("research_note") or ""
            if research_note:
                lines.append(f"- **券商观点**：{research_note}")
            comment = b.get("comment") or ""
            if comment:
                lines.append(f"- **智能点评**：{comment}")
            lines.append("")

    _sector_block("三、今日强势板块", sectors_strong)
    _sector_block("四、中等关注板块", sectors_medium)

    # ---------- 业绩预告 ----------
    lines.append("## 五、业绩预告")
    lines.append("")
    if forecasts:
        lines.append("| 代码 | 简称 | 预告类型 | 净利润变动区间 |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for f in forecasts:
            lo, up = f.get("change_lower"), f.get("change_upper")
            if lo is not None and up is not None:
                change = f"{_fmt(lo)}%~{_fmt(up)}%"
            elif lo is not None:
                change = f"{_fmt(lo)}%~"
            elif up is not None:
                change = f"~{_fmt(up)}%"
            else:
                change = "-"
            lines.append(
                f"| {_fmt(f.get('stock_code'))} | {_fmt(f.get('stock_name'))} | "
                f"{_fmt(f.get('forecast_type'))} | {change} |"
            )
    else:
        lines.append("（今日无业绩预告）")
    lines.append("")

    # ---------- 利好公告（高 / 中分组） ----------
    lines.append("## 六、利好公告")
    lines.append("")
    for section, key in (("高关注", "high_level"), ("中等关注", "medium_level")):
        rows = anns.get(key) or []
        lines.append(f"### {section}（{len(rows)} 条）")
        lines.append("")
        if not rows:
            lines.append("（无）")
            lines.append("")
            continue
        for r in rows:
            a = r.get("announcement") or {}
            analysis = r.get("analysis") or {}
            title_snippet = _fmt(a.get("title"), "")
            if title_snippet and len(title_snippet) > 60:
                title_snippet = title_snippet[:60] + "…"
            reason = analysis.get("reason") or ""
            if reason and len(reason) > 100:
                reason = reason[:100] + "…"
            line = f"- **{_fmt(a.get('stock_name'), _fmt(a.get('stock_code')))}**（{_fmt(a.get('stock_code'))}）：{title_snippet}"
            if reason:
                line += f" ｜ {reason}"
            lines.append(line)
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"> 本报告由智能投研信息引擎自动生成，生成日期 {date_str}。数据来自交易所公告与公开市场信息，仅供投资参考。")
    lines.append("")
    return "\n".join(lines)
