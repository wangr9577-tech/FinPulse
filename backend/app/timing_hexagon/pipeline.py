# -*- coding: utf-8 -*-
"""
择时六面图指标计算与合规流水线总控 (Pipeline)
==============================================
调用 01_数据清洗 -> 02_指标计算 -> 03_质量检查 完成择时指标的全流程合规计算。
"""
from pathlib import Path
import subprocess
import sys
import logging

logger = logging.getLogger("TimingHexagonPipeline")
BASE_DIR = Path(__file__).resolve().parent

SCRIPTS = [
    "01_数据清洗.py",
    "02_指标计算.py",
    "03_质量检查.py"
]

def run_timing_hexagon_pipeline() -> bool:
    """运行择时六面图数据清洗、指标计算与质量检查全流程"""
    logger.info("开始触发 择时六面图 全流程合规计算...")
    for script_name in SCRIPTS:
        script_path = BASE_DIR / script_name
        logger.info(f"正在执行: {script_name}...")
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=BASE_DIR,
            capture_output=True,
            text=True
        )
        if completed.returncode != 0:
            logger.error(f"脚本 {script_name} 执行失败 (退出码: {completed.returncode}):\n{completed.stderr}")
            return False
        logger.info(f"脚本 {script_name} 执行成功。")
    
    logger.info("择时六面图 34 项指标清洗、计算与质量校验全部顺利通过。")
    return True

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    success = run_timing_hexagon_pipeline()
    if not success:
        sys.exit(1)
