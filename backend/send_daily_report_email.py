# -*- coding: utf-8 -*-
"""
智能投研项目 - 每日研报邮件发送脚本 (backend/send_daily_report_email.py)
========================================================================
功能：
    将单日运行生成的智能投研研报 (PDF) 通过 QQ 邮箱 SMTP 自动发送至指定接收人。

实现说明：
    本脚本已重构为对通用邮件模块 (app.services.email_sender.send_report_email) 的
    薄封装，保留手动 CLI 用法 (python send_daily_report_email.py --receivers ...)。
    旧的 BACKEND_DIR 未定义 NameError 已移除，现统一从 app.core.config.settings
    读取 output 目录。多附件 (资讯/六面图/每日投资日报) 由新模块一并挂载。
"""
import sys
from pathlib import Path

from app.core.config import settings
from app.services.email_sender import send_report_email

DEFAULT_RECEIVERS = settings.DEFAULT_RECEIVERS


def find_latest_report_files():
    """查找 backend/output 目录下最新的 PDF 研报文件（按存在优先级 + 修改时间兜底）。

    返回 list[Path]：优先固定名 (market_insight_report.pdf)，其次最新时间戳文件。
    """
    output_dir = settings.OUTPUT_DIR
    candidates = []
    for name in ("market_insight_report.pdf", "timing_report.pdf"):
        p = output_dir / name
        if p.exists():
            candidates.append(p)
    if not candidates and output_dir.exists():
        pdf_files = sorted(output_dir.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True)
        candidates = pdf_files[:1]
    return candidates


def send_daily_report_email(
    pdf_paths: list[Path] | None = None,
    receivers: list | None = None,
    custom_subject: str | None = None,
) -> bool:
    """
    发送单日运行研报邮件

    :param pdf_paths: PDF 附件文件路径列表，若为 None 则自动查找最新 PDF
    :param receivers: 收件人邮箱列表
    :param custom_subject: 自定义邮件主题
    :return: 是否发送成功
    """
    if receivers is None:
        receivers = list(DEFAULT_RECEIVERS) if DEFAULT_RECEIVERS else []
    pdf_paths = pdf_paths or find_latest_report_files()

    today_str = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    subject = custom_subject or f"[智能投研单日报告] 国盛择时六面图与全量舆情推演 ({today_str})"
    return send_report_email(receivers=receivers, subject=subject, pdf_paths=pdf_paths, html_paths=None)


if __name__ == "__main__":
    import argparse
    import datetime
    parser = argparse.ArgumentParser(description="发送单日运行智能投研研报邮件")
    parser.add_argument("--receivers", nargs="+", default=DEFAULT_RECEIVERS, help="收件人邮箱列表")
    args = parser.parse_args()

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    success = send_daily_report_email(
        receivers=args.receivers,
        custom_subject=f"[智能投研单日报告] 国盛择时六面图与全量舆情推演 ({today})",
    )
    if success:
        print("[SUCCESS] 单日研报邮件已成功发送完毕。")
    else:
        print("[ERROR] 邮件发送失败，请检查相关日志信息。")
