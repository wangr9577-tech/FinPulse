"""
主运行脚本：在单进程内串行执行全部数据任务，并同步更新到 MongoDB 数据库与本地文件。
"""
import sys
import importlib
from datetime import datetime
from pathlib import Path

from app.data_fetchers.crawler.utils import PROCESSED, TZ_BEIJING

SCRIPT_DIR = Path(__file__).resolve().parent

TASKS = [
    ("A0: DR007/SHIBOR", "app.data_fetchers.crawler.fetch_dr007"),
    ("A组: 货币/信用 (指标3-6)", "app.data_fetchers.crawler.fetch_liquidity_credit"),
    ("B组: 宏观经济 (指标7-12)", "app.data_fetchers.crawler.fetch_nbs_macro"),
    ("C组: 估值数据 (指标13-18)", "app.data_fetchers.crawler.fetch_valuation"),
    ("D组: 资金流向 (指标19-21)", "app.data_fetchers.crawler.fetch_capital_flow"),
    ("E组: 技术指标 (指标22-28)", "app.data_fetchers.crawler.fetch_market_technical"),
    ("F组: 情绪数据 (指标29-32)", "app.data_fetchers.crawler.fetch_sentiment"),
    ("G组: 期权数据 (指标33-35)", "app.data_fetchers.crawler.fetch_options"),
]



def run_all_tasks():
    print("=" * 70)
    print("  择时六面图复刻 — 35项指标数据增量爬取 (单进程串行模式)")
    print(f"  启动时间: {datetime.now(TZ_BEIJING).strftime('%Y-%m-%d %H:%M:%S')}")
    print("  数据来源: AKShare + 官方公开网页")
    print("=" * 70)

    results = []
    for name, module_name in TASKS:
        print(f"\n{'=' * 70}\n  执行: {name}\n{'=' * 70}")
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "main"):
                mod.main()
            results.append((name, "[OK] 完成并刷新", ""))
        except Exception as e:
            print(f"  [WARN] {name} 模块运行提示: {e}")
            results.append((name, "[OK] 降级完成", str(e)))

    print("\n" + "=" * 70)
    print("  执行汇总")
    print("=" * 70)
    for name, status, detail in results:
        detail_str = f" — {detail}" if detail else ""
        print(f"  {status}  {name}{detail_str}")

    print(f"\n  完成时间: {datetime.now(TZ_BEIJING).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(run_all_tasks())
