"""整合器：公告分析结果 + 板块分析结果 → DailyReportData + 邮件正文摘要。"""
import html
from datetime import date

from app.stock_daily.config import settings
from app.stock_daily.models import DailyReportData, ForecastRow, ReportData, SectorAnalysis, StockPicks


def _esc(text) -> str:
    """HTML 转义外部来源文本，防注入/断表。"""
    return html.escape(str(text), quote=False)


def build_daily_report(
    ann_data: ReportData | None,
    sector_boards: list[SectorAnalysis],
    report_date: date,
    stock_picks: StockPicks | None = None,  # 新增：每日选股推荐
    forecasts: list | None = None,
) -> DailyReportData:
    """整合公告与板块数据，按分级拆出强/中列表（各限前 N）。"""
    strong = [b for b in sector_boards if b.grade == "强"][:settings.SECTOR_TOP_N_STRONG]
    medium = [b for b in sector_boards if b.grade == "中"][:settings.SECTOR_TOP_N_MEDIUM]
    return DailyReportData(
        date=report_date, announcements=ann_data,
        sectors_strong=strong, sectors_medium=medium,
        stock_picks=stock_picks,
        forecasts=forecasts or [],
    )


def _ann_rows(ann_data: ReportData) -> list[tuple[str, str]]:
    """利好公告推荐行：(代码, 简称)，按 高→中→低 排序取前 N。"""
    order = {"高": 0, "中": 1, "低": 2}
    rows = sorted(ann_data.full_list, key=lambda r: order.get(r.analysis.level, 9))
    return [(r.announcement.stock_code, r.announcement.stock_name)
            for r in rows[:settings.REPORT_TOP_N_RECOMMEND]]


def _sector_rows(boards: list[SectorAnalysis], top: int) -> list[tuple[str, str]]:
    """强势板块推荐行：(板块名(级), 领涨股)，按分数降序取前 N。"""
    out = []
    for b in sorted(boards, key=lambda b: b.score, reverse=True)[:top]:
        out.append((f"{b.board_name}（{b.grade}）", "、".join(b.leader_stocks) or "—"))
    return out


def _forecast_rows(forecasts: list[ForecastRow]) -> list[tuple[str, str, str, str]]:
    """业绩预告行：(代码, 简称, 预告类型, 净利润变动区间)。"""
    out = []
    for f in forecasts:
        if f.change_lower is not None and f.change_upper is not None:
            change = f"{f.change_lower:g}%~{f.change_upper:g}%"
        else:
            change = "-"
        out.append((f.stock_code, f.stock_name, f.forecast_type or "-", change))
    return out


def build_email_summary(daily: DailyReportData) -> str:
    """邮件正文 HTML：两张简短摘要表（利好公告推荐 / 强势板块+领涨股）。"""
    lines = ["<html><body style='font-family:system-ui;font-size:13px'>"]
    lines.append("<h3>今日利好公告推荐</h3>")
    lines.append("<table border='1' cellpadding='4' style='border-collapse:collapse'>"
                 "<tr><th>代码</th><th>简称</th></tr>")
    if daily.announcements:
        for code, name in _ann_rows(daily.announcements):
            lines.append(f"<tr><td>{_esc(code)}</td><td>{_esc(name) or '-'}</td></tr>")
    else:
        lines.append("<tr><td colspan='2'>（当日无利好公告）</td></tr>")
    lines.append("</table>")
    lines.append("<h3>今日业绩预告</h3>")
    if daily.forecasts:
        lines.append("<table border='1' cellpadding='4' style='border-collapse:collapse'>"
                     "<tr><th>代码</th><th>简称</th><th>预告类型</th><th>净利润变动</th></tr>")
        for code, name, ftype, change in _forecast_rows(daily.forecasts):
            lines.append(f"<tr><td>{_esc(code)}</td><td>{_esc(name) or '-'}</td>"
                         f"<td>{_esc(ftype)}</td><td>{_esc(change)}</td></tr>")
        lines.append("</table>")
    else:
        lines.append("<p>（当日无业绩预告）</p>")
    lines.append("<h3>今日强势板块（板块 / 领涨股）</h3>")
    lines.append("<table border='1' cellpadding='4' style='border-collapse:collapse'>"
                 "<tr><th>板块</th><th>领涨股</th></tr>")
    rows = (_sector_rows(daily.sectors_strong, settings.REPORT_TOP_N_RECOMMEND)
            + _sector_rows(daily.sectors_medium, settings.REPORT_TOP_N_RECOMMEND))
    if rows:
        for board, stock in rows:
            lines.append(f"<tr><td>{_esc(board)}</td><td>{_esc(stock)}</td></tr>")
    else:
        lines.append("<tr><td colspan='2'>（当日无强势板块）</td></tr>")
    lines.append("</table>")
    if daily.stock_picks:
        lines.append("<h3>今日选股推荐</h3>")
        if daily.stock_picks.picks:
            lines.append("<table border='1' cellpadding='4' style='border-collapse:collapse'>"
                         "<tr><th>代码</th><th>简称</th><th>推荐理由</th></tr>")
            for p in daily.stock_picks.picks:
                lines.append(f"<tr><td>{_esc(p.stock_code)}</td><td>{_esc(p.stock_name) or '-'}</td>"
                             f"<td>{_esc(p.reason)}</td></tr>")
            lines.append("</table>")
        else:
            lines.append(f"<p>{_esc(daily.stock_picks.note) or '（今日无选股推荐）'}</p>")
    lines.append("</body></html>")
    return "\n".join(lines)
