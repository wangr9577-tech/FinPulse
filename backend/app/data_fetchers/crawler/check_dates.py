"""检查 processed CSV 的日期、重复值、有效数值和新鲜度。"""
from datetime import datetime
from pathlib import Path
import json
import sys

import pandas as pd

from utils import TZ_BEIJING


PROCESSED = Path(__file__).resolve().parent.parent / "processed"
OUTPUT = Path(__file__).resolve().parent.parent / "metadata" / "date_check_results.json"
AS_OF_DATE = pd.Timestamp(datetime.now(TZ_BEIJING).date())
NON_VALUE_PATTERNS = ("date", "日期", "signal", "状态", "说明", "source", "来源")


def first_date_column(columns):
    return next(
        (column for column in columns if "date" in column.lower() or "日期" in column),
        None,
    )


def check_file(path):
    relative = str(path.relative_to(PROCESSED))
    result = {
        "file": relative,
        "status": "FAIL",
        "rows": 0,
        "min_date": "",
        "max_date": "",
        "duplicate_dates": 0,
        "value_columns": [],
        "non_null_value_count": 0,
        "all_values_null": True,
        "data_age_days": None,
        "starts_2008": False,
        "issues": [],
    }
    try:
        frame = pd.read_csv(path)
        result["rows"] = len(frame)
        if frame.empty:
            result["issues"].append("文件无数据行")
            return result

        date_col = first_date_column(frame.columns)
        if date_col is None:
            result["issues"].append("未找到日期列")
        else:
            dates = pd.to_datetime(frame[date_col], errors="coerce")
            if dates.isna().all():
                result["issues"].append("日期列全部无法解析")
            else:
                valid_dates = dates.dropna()
                min_date = valid_dates.min()
                max_date = valid_dates.max()
                duplicate_dates = int(valid_dates.duplicated().sum())
                result.update({
                    "min_date": min_date.strftime("%Y-%m-%d"),
                    "max_date": max_date.strftime("%Y-%m-%d"),
                    "duplicate_dates": duplicate_dates,
                    "data_age_days": int((AS_OF_DATE - max_date.normalize()).days),
                    "starts_2008": bool(min_date <= pd.Timestamp("2008-03-31")),
                })
                if dates.isna().any():
                    result["issues"].append(f"存在{int(dates.isna().sum())}个无效日期")
                if duplicate_dates:
                    result["issues"].append(f"存在{duplicate_dates}个重复日期")
                if not dates.dropna().is_monotonic_increasing:
                    result["issues"].append("日期未升序排列")

        value_columns = [
            column for column in frame.columns
            if not any(pattern in column.lower() for pattern in NON_VALUE_PATTERNS)
        ]
        numeric_values = frame[value_columns].apply(pd.to_numeric, errors="coerce")
        non_null_count = int(numeric_values.notna().sum().sum())
        result["value_columns"] = value_columns
        result["non_null_value_count"] = non_null_count
        result["all_values_null"] = non_null_count == 0
        if not value_columns:
            result["issues"].append("未找到可检查的数值列")
        elif non_null_count == 0:
            result["issues"].append("所有指标值均为空（占位文件不能视为完成）")

        result["status"] = "PASS" if not result["issues"] else "FAIL"
        return result
    except Exception as exc:
        result["issues"].append(f"{type(exc).__name__}: {str(exc)[:160]}")
        return result


results = [check_file(path) for path in sorted(PROCESSED.rglob("*.csv"))]
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(
    json.dumps(results, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

failed = [result for result in results if result["status"] == "FAIL"]
print(f"检查文件: {len(results)}；通过: {len(results) - len(failed)}；失败: {len(failed)}")
for result in failed:
    print(f"  [FAIL] {result['file']}: {'；'.join(result['issues'])}")
print(f"结果已保存: {OUTPUT}")
raise SystemExit(1 if failed else 0)
