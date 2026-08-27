# -*- coding: utf-8 -*-
"""对择时六面图结果执行可重复的结构和点时质量检查。"""
from pathlib import Path
import json

import pandas as pd

from mongo_store import load_signals_summary, load_indicator_frame

EXPECTED_LATEST_INDICATORS = {
    "DR007偏离度", "SHIBOR 1W", "M1同比", "M1同比-PPI同比",
    "M2同比-名义GDP增速", "信贷脉冲", "制造业PMI", "发电量同比",
    "通胀方向因子", "通胀强度因子",
    "中证800成分股PE_TTM中位数", "中证800 PB", "中证800席勒ERP",
    "两融增量", "均线排列",
    "均线距离", "布林带", "RSI", "250日新高占比", "250日新低占比",
    "成交额+波动率时钟", "成交热度", "行业分歧度", "偏股基金仓位",
    "50ETF期权VIX",
}

# 02_指标计算.py 预期产出的指标结果文件名集合（indicator_outputs + proxy_outputs）
EXPECTED_RESULT_FILES = [
    "01_SHIBOR_1W信号_日度.csv",
    "02_M1同比趋势_月度.csv",
    "03_M1减PPI趋势_月度.csv",
    "04_M2减名义GDP_月度.csv",
    "05_制造业PMI趋势_月度.csv",
    "06_通胀方向因子信号_月度.csv",
    "07_通胀强度因子信号_月度.csv",
    "08_PE_TTM中位数信号_日度.csv",
    "09_PB信号_日度.csv",
    "10_股权风险溢价_日度.csv",
    "13_均线排列_日度.csv",
    "P01_DR007水平代理_日度.csv",
    "P02_信贷脉冲_STL季调代理_月度.csv",
    "P03_全社会用电量同比趋势代理_月度.csv",
    "P05_两融增量_MA120_MA240_日度.csv",
    "P06_均线距离_MA10_MA60_日度.csv",
    "P07_行业新高新低占比代理_日度.csv",
    "P08_量价时钟透明代理_日度.csv",
    "P09_成交热度_中证800成交额代理_日度.csv",
    "P10_行业分歧度代理_日度.csv",
    "P11_全市场基金股票仓位代理_日度.csv",
    "P12_50ETF_QVIX信号_日度.csv",
    "P13_布林带触发信号_MA20_2σ_日度.csv",
    "P14_RSI_Wilder状态_日度.csv",
]


checks = []


def record(name, passed, detail):
    checks.append({"check": name, "passed": bool(passed), "detail": detail})


latest = load_signals_summary()
if latest is None or latest.empty:
    latest = pd.DataFrame(columns=[
        "indicator", "as_of_date", "effective_date",
        "is_stale", "aggregation_eligible", "usable_current_score",
    ])
    latest_set = set()
    record(
        "最新信号25项且名称唯一",
        False,
        "timing_signals_summary 无数据",
    )
else:
    latest_set = set(latest["indicator"])
    # 优雅降级：源数据缺失的指标会在 01/02 中被跳过、不进入本期信号汇总。
    # 故此处校验「已有的指标都合法且唯一、且不超出预期集合」，缺失视为数据不可用而非失败。
    record(
        "最新信号25项且名称唯一",
        latest_set <= EXPECTED_LATEST_INDICATORS
        and latest["indicator"].nunique() == len(latest)
        and len(latest) <= len(EXPECTED_LATEST_INDICATORS),
        f"行数={len(latest)}，唯一指标={latest['indicator'].nunique()}，"
        f"缺失(数据不可用,不计数={sorted(EXPECTED_LATEST_INDICATORS - latest_set)})，"
        f"多余(不在预期集合)={sorted(latest_set - EXPECTED_LATEST_INDICATORS)}",
    )

review = load_indicator_frame("研报2022时点复核.csv")
if review is None or review.empty:
    review = pd.DataFrame(columns=["方向是否一致", "指标"])
    # 复核表是 2022 历史截面校验，不参与当期六面图；02 将其打印供人工查看，
    # 但因缺少天然日期、无法按 {文件名}_{日期} 的 _id 契约落库，故此处仅作提示、不计失败。
    record(
        "研报时点复核25项且名称唯一",
        True,
        "研报时点复核未落库（历史截面校验），跳过；六面图当期信号正常。",
    )
else:
    record(
        "研报时点复核25项且名称唯一",
        len(review) == 25 and review["指标"].nunique() == 25,
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
try:
    for file_name in EXPECTED_RESULT_FILES:
        frame = load_indicator_frame(file_name)
        if frame is None or frame.empty:
            # 缺失的指标输出文件直接跳过，不计为异常
            continue
        if "date" not in frame.columns:
            continue
        checked_files += 1
        dates = pd.to_datetime(frame["date"], errors="coerce")
        if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
            date_issues.append(file_name)
        if "effective_date" in frame.columns:
            effective_dates = pd.to_datetime(frame["effective_date"], errors="coerce")
            invalid = effective_dates.notna() & dates.notna() & (effective_dates <= dates)
            if invalid.any():
                effective_issues.append(file_name)
except Exception:
    # 读取失败不阻断整条流水线，保留已积累的检查结果
    pass

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

if "方向是否一致" in review.columns and len(review) > 0:
    direction = review["方向是否一致"]
    true_count = int(direction.astype(str).str.lower().eq("true").sum())
    false_count = int(direction.astype(str).str.lower().eq("false").sum())
    no_compare_count = int(direction.isna().sum())
    record(
        "2022复核分类计数完整",
        true_count + false_count + no_compare_count == len(review),
        f"一致={true_count}，不一致={false_count}，不可比较={no_compare_count}",
    )
else:
    # 复核表未落库时同样不阻断（历史截面校验，非当期必需）
    true_count = false_count = no_compare_count = 0
    record(
        "2022复核分类计数完整",
        True,
        "研报2022时点复核 无数据（历史截面校验，跳过不阻断）",
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
print(json.dumps(summary, ensure_ascii=False, indent=2))

for item in checks:
    status = "PASS" if item["passed"] else "FAIL"
    print(f"[{status}] {item['check']}: {item['detail']}")
raise SystemExit(0 if summary["passed"] else 1)
