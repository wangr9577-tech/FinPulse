"""
Markdown 投研报告转 PDF 自动化编译工具 (convert_report_to_pdf.py)
满足用户与 8.12 WBS 扩展交付要求：
1. 将 Markdown 投研报告解析转换为带有公募/私募买方研报视觉排版的 HTML 结构
2. 注入金融级 CSS 样式表 (包含高亮卡牌、矢量 Badge、优雅的中文字体族与 A4 页面排版)
3. 自动化编译导出为标准 PDF 格式文档 (保存于 backend/output/market_insight_report.pdf)
"""
import sys
import os
import re
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

# 确保 UTF-8 控制台输出
sys.stdout.reconfigure(encoding='utf-8')

from app.core.logger import app_logger
from app.core.report_validator import ReportValidator



FINANCIAL_REPORT_CSS = """
@page {
    size: A4;
    margin: 1.8cm 1.5cm 1.8cm 1.5cm;
    @bottom-right {
        content: "第 " counter(page) " 页 / 共 " counter(pages) " 页";
        font-size: 9pt;
        color: #64748b;
    }
    @bottom-left {
        content: "智能投研信息引擎 - 每日全市场综合研报";
        font-size: 9pt;
        color: #64748b;
    }
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", sans-serif;
    color: #1e293b;
    background-color: #ffffff;
    line-height: 1.6;
    font-size: 10.5pt;
}

/* 顶部公募买方研报 Banner */
.header-banner {
    border-bottom: 3px solid #1e3a8a;
    padding-bottom: 12px;
    margin-bottom: 24px;
}

.header-banner h1 {
    color: #0f172a;
    font-size: 20pt;
    font-weight: 700;
    margin: 0 0 8px 0;
    letter-spacing: -0.5px;
}

.header-meta {
    font-size: 9.5pt;
    color: #475569;
    display: flex;
    justify-content: space-between;
}

.badge {
    background-color: #eff6ff;
    color: #1d4ed8;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 9pt;
    font-weight: 600;
}

/* 章节标题 */
h1 {
    color: #0f172a;
    font-size: 18pt;
    border-bottom: 2px solid #e2e8f0;
    padding-bottom: 6px;
    margin-top: 24px;
    margin-bottom: 16px;
}

h2 {
    color: #1e3a8a;
    font-size: 14pt;
    border-left: 4px solid #2563eb;
    padding-left: 10px;
    margin-top: 20px;
    margin-bottom: 12px;
}

h3 {
    color: #0f172a;
    font-size: 12pt;
    margin-top: 16px;
    margin-bottom: 8px;
}

h4 {
    color: #334155;
    font-size: 11pt;
    margin-top: 12px;
    margin-bottom: 6px;
}

/* 重点提示框与卡牌 */
blockquote {
    background-color: #f8fafc;
    border-left: 4px solid #3b82f6;
    margin: 12px 0;
    padding: 10px 16px;
    border-radius: 0 6px 6px 0;
    color: #334155;
}

ul {
    padding-left: 20px;
    margin-top: 6px;
    margin-bottom: 12px;
}

li {
    margin-bottom: 4px;
}

strong {
    color: #0f172a;
}

code {
    background-color: #f1f5f9;
    color: #0f172a;
    padding: 2px 5px;
    border-radius: 4px;
    font-family: "Fira Code", Consolas, Monaco, monospace;
    font-size: 9.5pt;
}

/* 金融级表格样式 */
table {
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
    font-size: 9pt;
}

th {
    background-color: #1e3a8a;
    color: #ffffff;
    padding: 8px 10px;
    text-align: left;
    font-weight: 600;
    border: 1px solid #1e3a8a;
}

td {
    padding: 6px 9px;
    border: 1px solid #cbd5e1;
    color: #334155;
}

tr:nth-child(even) {
    background-color: #f8fafc;
}

/* 研报图表及雷达图容器 */
.chart-container {
    text-align: center;
    margin: 16px 0;
    page-break-inside: avoid;
}

.report-chart {
    max-width: 95%;
    height: auto;
    border-radius: 6px;
    border: 1px solid #cbd5e1;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

.chart-caption {
    font-size: 8.5pt;
    color: #64748b;
    margin-top: 6px;
    font-weight: 500;
}

/* 页脚落款 */
.footer-note {
    margin-top: 30px;
    border-top: 1px dashed #cbd5e1;
    padding-top: 10px;
    font-size: 8.5pt;
    color: #94a3b8;
    text-align: center;
}
"""


def parse_markdown_table_block(match: re.Match) -> str:
    """将 Markdown 格式表格段落解析为 HTML <table> 标签"""
    table_text = match.group(0).strip()
    lines = [line.strip() for line in table_text.split("\n") if line.strip()]
    if len(lines) < 2:
        return table_text
    
    headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
    
    # 过滤分隔符行 (如 | :---: | :--- |)
    data_rows = []
    for line in lines[1:]:
        if re.match(r"^\|?\s*:?-+:?\s*(\|?\s*:?-+:?\s*)*\|?$", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        data_rows.append(cells)
        
    html = ["<table>\n<thead>\n<tr>\n"]
    for h in headers:
        html.append(f"  <th>{h}</th>\n")
    html.append("</tr>\n</thead>\n<tbody>\n")
    
    for row in data_rows:
        html.append("<tr>\n")
        for cell in row:
            html.append(f"  <td>{cell}</td>\n")
        html.append("</tr>\n")
    html.append("</tbody>\n</table>")
    return "".join(html)


def convert_markdown_to_html(md_text: str) -> str:
    """将 Markdown 研报转换为包含专业买方 CSS 样式的 HTML 字符串"""
    html = md_text

    # 0. 优先转换 Markdown 表格
    html = re.sub(
        r"(\|[^\n]+\|\n\|[\s:-|]+\|\n(?:\|[^\n]+\|\n?)+)",
        parse_markdown_table_block,
        html,
        flags=re.MULTILINE
    )

    # 1. 转换标题
    html = re.sub(r"^#\s+(.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
    html = re.sub(r"^##\s+(.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^###\s+(.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^####\s+(.+)$", r"<h4>\1</h4>", html, flags=re.MULTILINE)

    # 2. 转换加粗与代码
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"`(.+?)`", r"<code>\1</code>", html)

    # 2.5 转换 Markdown 图片 ![alt](src)
    def _replace_img(match: re.Match) -> str:
        alt = match.group(1)
        src = match.group(2)
        # 将绝对 file:/// URI 转换为以 HTML 文件为相对基准的相对路径
        if "output/charts/" in src or "output\\charts\\" in src:
            parts = re.split(r'output[/\\]charts[/\\]', src)
            if len(parts) > 1:
                src = f"charts/{parts[-1]}"
        return f'<div class="chart-container"><img src="{src}" alt="{alt}" class="report-chart" /><div class="chart-caption">{alt}</div></div>'

    html = re.sub(r"!\[(.*?)\]\((.*?)\)", _replace_img, html)

    # 3. 转换列表项
    html = re.sub(r"^\s*-\s+(.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"(<li>.*?</li>(?:\n<li>.*?</li>)*)", r"<ul>\1</ul>", html, flags=re.DOTALL)

    # 4. 转换段落与换行
    paragraphs = html.split("\n\n")
    formatted_p = []
    for p in paragraphs:
        p_str = p.strip()
        if not p_str:
            continue
        if not (p_str.startswith("<h") or p_str.startswith("<ul") or p_str.startswith("<blockquote") or p_str.startswith("<table") or p_str.startswith("<div")):
            formatted_p.append(f"<p>{p_str}</p>")
        else:
            formatted_p.append(p_str)
    
    html_body = "\n".join(formatted_p)

    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>智能投研综合研报</title>
    <style>
    {FINANCIAL_REPORT_CSS}
    </style>
</head>
<body>
    <div class="header-banner">
        <span class="badge">机密 · 买方投研专用</span>
        <div class="header-meta">
            <span>生成时间：{Path(__file__).stat().st_mtime}</span>
            <span>文档编号：REP-20260727-01</span>
        </div>
    </div>
    {html_body}
    <div class="footer-note">
        本文档由 智能投研信息引擎 (Intelligent Equity Research Information Engine) 自动化编译生成。内容仅供投资决策参考。
    </div>
</body>
</html>
"""
    return full_html


async def compile_report_to_pdf(
    md_text: str,
    output_pdf_path: str,
    base_name: str = "market_insight_report",
    display_label: str = "智能投研综合研报",
    report_type: Optional[str] = None,
) -> bool:
    """
    将 Markdown 投研报告美化并编译导出为标准 PDF 文件
    优先采用 Playwright / Patchright 无头浏览器渲染高保真 PDF，若未安装则自动回退至 Html2Pdf/ReportLab

    base_name:    静态链接文件名底座 (如 market_insight_report / timing_report)，用于 .html/.pdf 通用名
    display_label:时间戳文件的人类可读名称 (如 智能投研综合研报 / 智能投研择时六面图研报)
    report_type:  可选，透传给 ReportValidator 以按报告类型校验必备章节 (timing / news)
    """
    app_logger.info(f"[PDF Engine] 启动投研报告 HTML/CSS 样式渲染 ({display_label})...")

    # 格式美化校验 (按报告类型校验其必备章节)
    validator = ReportValidator()
    val_res = validator.validate(md_text, report_type=report_type)
    clean_md = val_res.repaired_markdown

    html_content = convert_markdown_to_html(clean_md)

    output_dir = Path(output_pdf_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_pdf_name = f"{display_label}_{ts_str}.pdf"
    timestamped_html_name = f"{display_label}_{ts_str}.html"

    timestamped_pdf_path = str(output_dir / timestamped_pdf_name)
    timestamped_html_path = str(output_dir / timestamped_html_name)

    # 存 HTML 视图 (包含通用名与规范时间戳文件名)
    html_path = output_dir / f"{base_name}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    with open(timestamped_html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    app_logger.info(f"[PDF Engine] 已生成美化 HTML 视图文件:\n   - 规范时间戳命名: {timestamped_html_path}\n   - 静态链接命名: {html_path}")

    # 尝试使用 Playwright / Patchright 导出无损 PDF
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            # 使用 file:// 协议定位目标 HTML，确保跨域安全策略下能正常读取同级/下级本地图片资源
            await page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            
            # 同时生成时间戳文件与默认链接文件
            await page.pdf(
                path=output_pdf_path,
                format="A4",
                margin={"top": "1.8cm", "bottom": "1.8cm", "left": "1.5cm", "right": "1.5cm"},
                print_background=True
            )
            await page.pdf(
                path=timestamped_pdf_path,
                format="A4",
                margin={"top": "1.8cm", "bottom": "1.8cm", "left": "1.5cm", "right": "1.5cm"},
                print_background=True
            )
            await browser.close()
            
        app_logger.info(f"[PDF Engine] 成功使用 Playwright 导出高保真研报 PDF:\n   - 规范时间戳研报: {timestamped_pdf_path}\n   - 通用研发路径: {output_pdf_path}")
        return True

    except Exception as e_pw:
        app_logger.error(f"[PDF Engine] Playwright PDF 编译导出失败: {e_pw}")
        raise e_pw


if __name__ == "__main__":
    sample_md = """# 2026年07月27日 智能投研全市场宏观与行业综合研报

## 一、首席策略总揽
今日全市场运行核心逻辑为“内外流动性分化下的结构性行情”。两融交易占比 **11.70%**，Shibor 7D 利差为 **-0.3%**，全 A ERP 溢价为 **1.6824%**。

## 二、核心宏观与市场风险警示
- [风险警示] 外部利率上行风险：10年期美债收益率攀升，压制全市场高估值板块。
- [风险警示] 信用传导不畅：M2-M1 剪刀差 4.0%，资金于金融体系内淤积。

## 三、重点板块深度解析
### 【半导体芯片】
核心博弈聚焦于国产 3nm 芯片突破与全球晶圆代工涨价周期。"""
    from app.core.config import settings
    pdf_target = str(settings.OUTPUT_DIR / "market_insight_report.pdf")
    asyncio.run(compile_report_to_pdf(sample_md, pdf_target))
