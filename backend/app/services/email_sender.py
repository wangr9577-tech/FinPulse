"""
通用研报邮件发送模块 (app/services/email_sender.py)
========================================================================
从系统核心配置中心 (app.core.config.settings) 读取 SMTP 服务配置，支持：
  1. 一次挂载多个 PDF 附件
  2. 自动把发件人自身地址加入收件人（去重，尽量避免发给自己的服务器拒绝）
  3. 不向调用方抛异常：失败返回 False 并记日志，单步失败不影响整体流水线

供「每日自动运行」编排器 (services/daily_auto_run.py) 复用；旧脚本
send_daily_report_email.py 重构为薄封装转发到本模块（保留手动 CLI 用法）。
"""
import smtplib
import datetime
from pathlib import Path
from typing import Optional

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.header import Header
from email.utils import formataddr

from app.core.config import settings
from app.core.logger import app_logger


def _attach_pdf(msg: MIMEMultipart, pdf_path: Path, today_str: str) -> bool:
    """挂载单个 PDF 附件；失败记日志返回 False，不抛出。"""
    try:
        with open(pdf_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", pdf_path.name))
        msg.attach(part)
        app_logger.info(f"[EMAIL] 挂载 PDF 附件成功: {pdf_path.name}")
        return True
    except Exception as e:
        app_logger.error(f"[EMAIL] 挂载 PDF 附件失败 ({pdf_path.name}): {e!r}")
        return False


def send_report_email(
    receivers: list[str],
    subject: str,
    pdf_paths: list[Path],
    html_paths: Optional[list[Path]] = None,
    body_text: str = "",
) -> bool:
    """发送一封带多个 PDF 附件的研报邮件。

    :param receivers:  收件人邮箱列表（将自动并入发件人自身并去重）
    :param subject:    邮件主题
    :param pdf_paths:  要挂载的 PDF 附件路径列表（存在才挂载）
    :param html_paths: 预留 HTML 附件（当前不挂载，仅记录存在性）
    :param body_text:  纯文本正文，默认留空
    :return: 是否发送成功（SMTP 成功返回 True；任一步失败返回 False）
    """
    smtp_server = settings.SMTP_SERVER
    smtp_port = settings.SMTP_PORT
    sender_email = settings.SMTP_SENDER_EMAIL
    auth_code = settings.SMTP_AUTH_CODE

    if not (smtp_server and smtp_port and sender_email and auth_code):
        app_logger.error("[EMAIL] SMTP 配置不完整 (SMTP_SERVER/SMTP_PORT/SENDER/AUTH_CODE 缺失)，跳过发送。")
        return False

    # 收件人列表去重，并把发件人自身也加入（避免某些 SMTP 拒发给自己未列出的地址）
    rcv = list(dict.fromkeys([r.strip() for r in receivers if r and r.strip()]))
    if sender_email and sender_email not in rcv:
        rcv.append(sender_email)
    if not rcv:
        app_logger.error("[EMAIL] 无有效收件人，跳过发送。")
        return False

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    msg = MIMEMultipart("mixed")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr(("智能投研引擎", sender_email))
    msg["To"] = ", ".join(rcv)
    msg.attach(MIMEText(body_text or "", "plain", "utf-8"))

    attached = 0
    for p in (pdf_paths or []):
        p = Path(p)
        if p.exists() and _attach_pdf(msg, p, today_str):
            attached += 1
    if attached == 0:
        app_logger.warning("[EMAIL] 无有效 PDF 附件可挂载，仅发送正文邮件。")
    if html_paths:
        app_logger.info(f"[EMAIL] 收到 HTML 附件请求 {len(html_paths)} 个（当前统一挂 PDF，忽略）。")

    app_logger.info(f"[EMAIL] 正在通过 {smtp_server}:{smtp_port} 发送研报邮件至 {rcv}...")
    try:
        server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
        server.login(sender_email, auth_code)
        server.sendmail(sender_email, rcv, msg.as_string())
        server.quit()
        app_logger.info(f"[EMAIL] 邮件发送成功，已投递至: {', '.join(rcv)}，附件 {attached} 个。")
        return True
    except Exception as e_send:
        app_logger.error(f"[EMAIL] 邮件发送失败: {e_send!r}")
        return False
