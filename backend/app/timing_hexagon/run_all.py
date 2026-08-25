# -*- coding: utf-8 -*-
"""依次执行数据清洗、指标计算和质量检查。"""
from pathlib import Path
import subprocess
import sys


BASE_DIR = Path(__file__).resolve().parent
SCRIPTS = ["01_数据清洗.py", "02_指标计算.py", "03_质量检查.py"]

for script_name in SCRIPTS:
    print(f"\n=== 运行 {script_name} ===")
    completed = subprocess.run(
        [sys.executable, str(BASE_DIR / script_name)],
        cwd=BASE_DIR,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)

print("\n全部步骤完成，质量检查通过。")
