# -*- coding: utf-8 -*-
"""
智能投研项目 - 每日早上 07:00 定时调度与邮件发送脚本 (backend/daily_scheduler_7am.py)
===================================================================================
功能：
1. 放置在 backend 目录下；
2. 每日早上 07:00 自动启动全自动化单日流水线 (run_end_to_end_pipeline 过去24小时数据)；
3. 全自动生成择时六面图研报并美化排版、编译导出 PDF 附件；
4. 调用 send_daily_report_email() 将单日研报通过 QQ 邮箱 SMTP 精准发送至团队订阅邮箱。

使用方式：
- 常驻定时模式 (默认，每日 07:00 自动运行):
    python backend/daily_scheduler_7am.py
    # 或在 backend 目录下:
    python daily_scheduler_7am.py

- 立即执行一次 (测试/手动触发模式):
    python backend/daily_scheduler_7am.py --now
"""

import sys
import os
import time
import datetime
from pathlib import Path

# 强制控制台 UTF-8 输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from app.core.logger import app_logger
from scripts.run_end_to_end_pipeline import run_end_to_end_pipeline
from send_daily_report_email import send_daily_report_email



def execute_daily_task():
    """执行单日研报全流程流水线并发送邮件"""
    app_logger.info("=" * 80)
    app_logger.info("[07:00 定时任务触发] 启动单日智能投研流水线与邮件自动分发...")
    app_logger.info(f" 触发时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    app_logger.info("=" * 80)

    # 1. 跑通单日全自动化流水线 (分析过去 24 小时数据)
    try:
        app_logger.info("[STEP 1/2] 正在运行单日全自动化投研流水线 (数据时间窗口来自 config 配置)...")
        run_end_to_end_pipeline()
        app_logger.info("[STEP 1/2] 单日研报生成与 PDF 编译导出成功！")

    except Exception as e_pipeline:
        app_logger.error(f"[STEP 1/2] 研报流水线运行异常: {e_pipeline}")
        # 即使流水线局部报警，仍尝试发送已有或最新研报

    # 2. 自动发送研报邮件
    try:
        app_logger.info("[STEP 2/2] 正在发送单日研报邮件至默认团队订阅邮箱...")
        success = send_daily_report_email()
        if success:
            app_logger.info("[STEP 2/2] 单日研报邮件发送成功！")
        else:
            app_logger.warning("[STEP 2/2] 研报邮件发送未能完全成功，请检查 SMTP 状态。")
    except Exception as e_email:
        app_logger.error(f"[STEP 2/2] 邮件分发脚本异常: {e_email}")

    app_logger.info("=" * 80 + "\n")


def start_scheduler(target_time_str: str = "07:00"):
    """
    常驻定时调度器
    :param target_time_str: 每日触发时间，格式为 "HH:MM"，默认 "07:00"
    """
    target_hour, target_minute = map(int, target_time_str.split(":"))
    app_logger.info("=" * 80)
    app_logger.info(f"[定时服务启动] 智能投研每日 07:00 定时调度服务启动 (目标时间: 每日 {target_time_str})")
    app_logger.info(" 监控服务开启中，按 Ctrl+C 退出进程...")
    app_logger.info("=" * 80 + "\n")

    last_executed_date = None

    while True:
        try:
            now = datetime.datetime.now()
            today_date = now.date()

            # 判断是否到达每日的目标时间 (例如 07:00)，且今天尚未执行过
            if (
                now.hour == target_hour
                and now.minute == target_minute
                and last_executed_date != today_date
            ):
                last_executed_date = today_date
                execute_daily_task()

            # 轮询间隔 15 秒
            time.sleep(15)
        except KeyboardInterrupt:
            app_logger.info("[退出] 接收到终止信号，定时调度器安全退出。")
            break
        except Exception as e_loop:
            app_logger.error(f"[异常] 调度主循环发生异常: {e_loop}")
            time.sleep(30)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="每日早上 07:00 定时运行研报流水线与邮件分发服务")
    parser.add_argument("--now", action="store_true", help="立即执行一次单日任务 (不进行 07:00 定时等待)")
    parser.add_argument("--time", type=str, default="07:00", help="设置每日触发的时间 (格式 HH:MM, 默认 07:00)")
    args = parser.parse_args()

    if args.now:
        app_logger.info("🚀 [手动/测试模式] 立即执行单日任务...")
        execute_daily_task()
    else:
        start_scheduler(target_time_str=args.time)
