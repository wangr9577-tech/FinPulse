# -*- coding: utf-8 -*-
"""对择时六面图结果执行可重复的结构和点时质量检查。"""
from pathlib import Path
import json

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent.parent / "data"
RESULT_DIR = BASE_DIR / "results"
OUTPUT_DIRS = [
    RESULT_DIR / "indicator_outputs",
    RESULT_DIR / "proxy_outputs",
]

EXPECTED_LATEST_INDICATORS = {
    "DR007偏离度", "SHIBOR 1W", "M1同比", "M1同比-PPI同比",
    "M2同比-名义GDP增速", "信贷脉冲", "制造业PMI", "发电量同比",
    "库存周期", "A股景气度指数", "通胀方向因子", "通胀强度因子",
    "中证800成分股PE_TTM中位数", "中证800股息率", "中证800 PB",
    "中证800股权风险溢价", "中证800 DCF估值", "AIAE",
    "A股账户新增开户数", "两融增量", "均线排列",
    "均线距离", "布林带", "RSI", "250日新高占比", "250日新低占比",
    "成交额+波动率时钟", "成交热度", "行业分歧度", "偏股基金仓位",
    "东方财富NLP情绪", "期权认购认沽成交比率CPR", "50ETF期权VIX",
    "50ETF期权SKEW",
}


checks = []


def record(name, passed, detail):
    checks.append({"check": name, "passed": bool(passed), "detail": detail})


latest = pd.read_csv(RESULT_DIR / "最新信号汇总.csv", encoding="utf-8-sig")
review = pd.read_csv(RESULT_DIR / "研报2022时点复核.csv", encoding="utf-8-sig")

latest_set = set(latest["indicator"])
record(
    "最新信号34项且名称唯一",
    len(latest) == 34 and latest["indicator"].nunique() == 34
    and latest_set == EXPECTED_LATEST_INDICATORS,
    f"行数={len(latest)}，唯一指标={latest['indicator'].nunique()}，"
    f"缺失={sorted(EXPECTED_LATEST_INDICATORS - latest_set)}，"
    f"多余={sorted(latest_set - EXPECTED_LATEST_INDICATORS)}",
)
record(
    "研报时点复核34项且名称唯一",
    len(review) == 34 and review["指标"].nunique() == 34,
    f"行数={len(review)}，唯一指标={review['指标'].nunique()}",
)
record(
    "最新汇总使用统一截面",
    latest["as_of_date"].nunique() == 1,
    f"截面={sorted(latest['as_of_date'].dropna().astype(str).unique())}",
)

stale = latest["is_stale"].astype(str).str.lower().eq("true")
eligible = latest["aggregation_eligible"].astype(str).str.lower().eq("true")
usable = pd.to_numeric(latest["usable_current_score"], errors="coerce").notna()
record(
    "不可用或过期指标不进入当前可用分数",
    not (usable & (~eligible | stale)).any(),
    f"违规行数={int((usable & (~eligible | stale)).sum())}",
)

as_of = pd.to_datetime(latest["as_of_date"], errors="coerce")
effective = pd.to_datetime(latest["effective_date"], errors="coerce")
record(
    "当前可用分数均已在截面日前生效",
    not (usable & (effective > as_of)).any(),
    f"违规行数={int((usable & (effective > as_of)).sum())}",
)

date_issues = []
effective_issues = []
checked_files = 0
for folder in OUTPUT_DIRS:
    for path in sorted(folder.glob("*.csv")):
        frame = pd.read_csv(path, encoding="utf-8-sig")
        if "date" not in frame.columns:
            continue
        checked_files += 1
        dates = pd.to_datetime(frame["date"], errors="coerce")
        if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
            date_issues.append(path.name)
        if "effective_date" in frame.columns:
            effective_dates = pd.to_datetime(frame["effective_date"], errors="coerce")
            invalid = effective_dates.notna() & dates.notna() & (effective_dates <= dates)
            if invalid.any():
                effective_issues.append(path.name)

record(
    "指标输出日期有效、唯一且升序",
    not date_issues,
    f"检查文件={checked_files}，异常={date_issues}",
)
record(
    "生效日期严格晚于观测日期",
    not effective_issues,
    f"异常={effective_issues}",
)

SCRIPT_DIR = Path(__file__).resolve().parent
source = (SCRIPT_DIR / "02_指标计算.py").read_text(encoding="utf-8")
forbidden = [
    'limit_direction="both"',
    "limit_direction='both'",
    ".bfill(",
]
found = [pattern for pattern in forbidden if pattern in source]
record(
    "未发现明确双向填充未来数据",
    not found,
    f"命中={found}",
)

direction = review["方向是否一致"]
true_count = int(direction.astype(str).str.lower().eq("true").sum())
false_count = int(direction.astype(str).str.lower().eq("false").sum())
no_compare_count = int(direction.isna().sum())
record(
    "2022复核分类计数完整",
    true_count + false_count + no_compare_count == 34,
    f"一致={true_count}，不一致={false_count}，不可比较={no_compare_count}",
)

summary = {
    "passed": all(item["passed"] for item in checks),
    "checks": checks,
    "review_direction_counts": {
        "一致": true_count,
        "不一致": false_count,
        "不可比较": no_compare_count,
    },
}
(RESULT_DIR / "质量检查汇总.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

for item in checks:
    status = "PASS" if item["passed"] else "FAIL"
    print(f"[{status}] {item['check']}: {item['detail']}")
raise SystemExit(0 if summary["passed"] else 1)
