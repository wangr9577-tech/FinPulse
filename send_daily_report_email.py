# -*- coding: utf-8 -*-
"""
智能投研项目 - 每日研报邮件发送脚本 (backend/send_daily_report_email.py)
========================================================================
功能：
    将单日运行生成的智能投研研报 (HTML / PDF) 通过 QQ 邮箱 SMTP 自动发送至指定接收人。

发件配置：
    优先从环境变量 (.env) 中读取：
    - SMTP_SERVER: SMTP 服务器地址 (如 smtp.qq.com)
    - SMTP_PORT: 端口号 (如 465 SSL)
    - SMTP_SENDER_EMAIL: 发件人邮箱账号
    - SMTP_AUTH_CODE: 发件人邮箱授权码/密码
    - DEFAULT_RECEIVERS: 默认收件人列表 (逗号分隔)
"""

import sys
import os
import smtplib
import datetime
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.header import Header
from email.utils import formataddr
from app.core.config import settings
from app.core.logger import app_logger

# 统一从系统核心配置中心 (app.core.config.settings) 获取邮件服务配置
SMTP_SERVER = settings.SMTP_SERVER
SMTP_PORT = settings.SMTP_PORT
SENDER_EMAIL = settings.SMTP_SENDER_EMAIL
AUTH_CODE = settings.SMTP_AUTH_CODE
DEFAULT_RECEIVERS = settings.DEFAULT_RECEIVERS or ["395399805@qq.com", "kfzhong@sina.com"]



def find_latest_report_files():
    """查找 backend/output 目录下最新的 PDF 研报和 HTML 视图文件"""
    output_dir = BACKEND_DIR / "output"
    pdf_path = output_dir / "market_insight_report.pdf"
    html_path = output_dir / "market_insight_report.html"

    # 如果默认名称不存在，查找最新的带时间戳的 pdf/html 文件
    if not pdf_path.exists() and output_dir.exists():
        pdf_files = sorted(output_dir.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True)
        if pdf_files:
            pdf_path = pdf_files[0]

    if not html_path.exists() and output_dir.exists():
        html_files = sorted(output_dir.glob("*.html"), key=lambda x: x.stat().st_mtime, reverse=True)
        if html_files:
            html_path = html_files[0]

    return pdf_path, html_path


def send_daily_report_email(
    pdf_path: Path = None,
    html_path: Path = None,
    receivers: list = None,
    custom_subject: str = None
) -> bool:
    """
    发送单日运行研报邮件

    :param pdf_path: PDF 附件文件路径，若为 None 则自动查找最新 PDF
    :param html_path: HTML 正文预览文件路径
    :param receivers: 收件人邮箱列表
    :param custom_subject: 自定义邮件主题
    :return: 是否发送成功
    """
    if receivers is None:
        receivers = DEFAULT_RECEIVERS

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # 定位研报文件
    default_pdf, default_html = find_latest_report_files()
    target_pdf = pdf_path or default_pdf
    target_html = html_path or default_html

    # 构建邮件主体
    msg = MIMEMultipart("mixed")
    subject = custom_subject or f"⚡ 智能投研单日报告 | 国盛择时六面图与全量舆情推演 ({today_str})"
    msg["Subject"] = Header(subject, "utf-8")
    
    # 使用 formataddr 规范 RFC5322 From 与 To 头
    msg["From"] = formataddr(("智能投研引擎", SENDER_EMAIL))
    msg["To"] = ", ".join(receivers)

    # 构建 HTML 邮件正文
    html_content = ""
    if target_html and target_html.exists():
        try:
            with open(target_html, "r", encoding="utf-8") as f:
                html_content = f.read()
        except Exception as e:
            app_logger.warning(f"[EMAIL] 读取 HTML 视图文件失败: {e}")

    if not html_content:
        html_content = f"""
        <html>
        <body style="font-family: Arial, 'PingFang SC', sans-serif; color: #333; line-height: 1.6;">
            <div style="max-width: 650px; margin: 20px auto; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
                <div style="background: linear-gradient(135deg, #1e293b, #0f172a); color: #fff; padding: 24px; text-align: center;">
                    <h1 style="margin: 0; font-size: 22px; letter-spacing: 1px;">⚡ 智能投研每日报告</h1>
                    <p style="margin: 6px 0 0 0; color: #94a3b8; font-size: 14px;">国盛证券择时六面图 & 28大媒体舆情推演 | {today_str}</p>
                </div>
                <div style="padding: 24px; background-color: #ffffff;">
                    <p>尊贵的投研团队 / 订阅用户：</p>
                    <p>您好！单日智能投研自动化流水线已运行完成。附件中为您呈送最新的高保真 PDF 金融研报。</p>
                    <div style="background-color: #f8fafc; border-left: 4px solid #3b82f6; padding: 16px; margin: 20px 0; border-radius: 0 6px 6px 0;">
                        <h4 style="margin: 0 0 8px 0; color: #1e3a8a;">📊 本期研报亮点</h4>
                        <ul style="margin: 0; padding-left: 20px; color: #475569;">
                            <li><b>全量舆情抓取</b>：覆盖 28 大核心财经媒体与专业投研站点增量快讯。</li>
                            <li><b>择时六面图引擎</b>：35 项定量指标无未来函数标准化清洗与计算。</li>
                            <li><b>AI 多节点推演</b>：Analyst Agent 融合真实资金证据与板块连锁逻辑统稿。</li>
                        </ul>
                    </div>
                    <p>详情请查看随信附带的 <b>market_insight_report.pdf</b> 附件。</p>
                </div>
                <div style="background-color: #f1f5f9; padding: 12px 24px; text-align: center; color: #64748b; font-size: 12px;">
                    本邮件由 智能投研信息引擎 自动化发送，请勿直接回复。
                </div>
            </div>
        </body>
        </html>
        """

    msg.attach(MIMEText(html_content, "html", "utf-8"))

    # 挂载 PDF 附件
    if target_pdf and target_pdf.exists():
        try:
            with open(target_pdf, "rb") as f:
                pdf_part = MIMEApplication(f.read(), _subtype="pdf")
                pdf_filename = f"market_insight_report_{today_str}.pdf"
                pdf_part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", pdf_filename))
                msg.attach(pdf_part)
                app_logger.info(f"[EMAIL] 成功挂载 PDF 研报附件: {target_pdf.name}")
        except Exception as e_pdf:
            app_logger.error(f"[EMAIL] 挂载 PDF 附件失败: {e_pdf}")
    else:
        app_logger.warning(f"[EMAIL] 未找到研报 PDF 附件 ({target_pdf})，仅发送正文邮件。")

    # 执行 SMTP 发送
    app_logger.info(f"[EMAIL] 正在通过 {SMTP_SERVER}:{SMTP_PORT} 发送单日研报邮件至 {receivers}...")
    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30)
        server.login(SENDER_EMAIL, AUTH_CODE)
        server.sendmail(SENDER_EMAIL, receivers, msg.as_string())
        server.quit()
        app_logger.info(f"[EMAIL] 邮件发送成功！已成功投递至: {', '.join(receivers)}")
        return True
    except Exception as e_send:
        app_logger.error(f"[EMAIL] 邮件发送失败: {e_send}")
        return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="发送单日运行智能投研研报邮件")
    parser.add_argument("--receivers", nargs="+", default=DEFAULT_RECEIVERS, help="收件人邮箱列表")
    args = parser.parse_args()

    app_logger.info("[EMAIL] 启动单日研报邮件发送脚本...")
    success = send_daily_report_email(receivers=args.receivers)
    if success:
        print("[SUCCESS] 单日研报邮件已成功发送完毕。")
    else:
        print("[ERROR] 邮件发送失败，请检查相关日志信息。")
