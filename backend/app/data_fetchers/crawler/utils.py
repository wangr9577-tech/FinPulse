"""
通用工具模块：请求重试、原始落盘、数据处理辅助函数
来源：择时六面图复刻_数据获取与整理工作手册_无Wind版 附录A
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib
import json
import pandas as pd
import numpy as np
from tenacity import retry, stop_after_attempt, wait_exponential
import httpx

# 路径配置
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
RAW = BASE_DIR / "raw"
PROCESSED = BASE_DIR / "processed"
METADATA = BASE_DIR / "metadata"
LOGS = BASE_DIR / "logs"

# 北京时间
TZ_BEIJING = timezone(timedelta(hours=8))


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=20))
def fetch_bytes(url: str, params: dict | None = None) -> tuple[bytes, dict]:
    """带重试的HTTP GET请求，返回内容和元数据"""
    headers = {"User-Agent": "research-replication/1.0 (contact: team)"}
    with httpx.Client(timeout=30, follow_redirects=True, headers=headers) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
    meta = {
        "url": str(r.url),
        "status": r.status_code,
        "retrieved_at": datetime.now(TZ_BEIJING).isoformat(),
        "sha256": hashlib.sha256(r.content).hexdigest(),
        "content_type": r.headers.get("content-type"),
    }
    return r.content, meta


def save_raw(source: str, dataset: str, content: bytes, meta: dict, suffix: str = "bin"):
    """落盘原始数据到 raw/<source>/<dataset>/ 目录"""
    ts = datetime.now(TZ_BEIJING).strftime("%Y%m%d_%H%M%S")
    folder = RAW / source / dataset
    folder.mkdir(parents=True, exist_ok=True)
    data_path = folder / f"{dataset}_{ts}.{suffix}"
    data_path.write_bytes(content)
    # 写元数据
    meta_path = data_path.with_suffix(data_path.suffix + ".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return data_path


def expand_by_release_date(macro: pd.DataFrame, trading_days: pd.DatetimeIndex) -> pd.DataFrame:
    """按发布日期展开宏观数据到交易日，防止前视偏差"""
    x = macro.sort_values("release_date").copy()
    x["release_date"] = pd.to_datetime(x["release_date"])
    calendar = pd.DataFrame({"date": trading_days}).sort_values("date")
    out = pd.merge_asof(
        calendar, x,
        left_on="date", right_on="release_date",
        direction="backward", allow_exact_matches=True,
    )
    return out


def add_realtime_thresholds(s: pd.Series, min_obs: int = 60, z_window: int = 1260) -> pd.DataFrame:
    """扩展窗口分位数与滚动标准化（实时回测版本）"""
    q10 = s.expanding(min_periods=min_obs).quantile(0.10)
    q90 = s.expanding(min_periods=min_obs).quantile(0.90)
    mean = s.rolling(z_window, min_periods=min_obs).mean()
    std = s.rolling(z_window, min_periods=min_obs).std(ddof=1)
    z = (s - mean) / std
    return pd.DataFrame({"value": s, "q10_rt": q10, "q90_rt": q90, "z5y": z})


def add_full_sample_thresholds(s: pd.Series) -> pd.DataFrame:
    """全样本分位数（图形展示版本，有前视）"""
    q10_full = s.quantile(0.10)
    q90_full = s.quantile(0.90)
    mean_full = s.mean()
    std_full = s.std(ddof=1)
    z = (s - mean_full) / std_full
    return pd.DataFrame({
        "value": s,
        "q10_full": q10_full,
        "q90_full": q90_full,
        "z_full": z,
    })


def qc_assertions(df: pd.DataFrame, date_col: str = "date"):
    """数据质量断言"""
    assert df[date_col].notna().all(), f"{date_col} missing"
    assert not df[date_col].duplicated().any(), f"duplicate {date_col}"
    assert df[date_col].is_monotonic_increasing, f"{date_col} not sorted"


def parse_chinese_date(series: 'pd.Series') -> 'pd.Series':
    """解析中文日期格式如'2024年01月份' -> datetime"""
    cleaned = series.astype(str).str.replace(r'[年月日份]', '', regex=True).str.strip()
    result = pd.to_datetime(cleaned, format='%Y%m', errors='coerce')
    mask = result.isna()
    if mask.any():
        result.loc[mask] = pd.to_datetime(cleaned.loc[mask], format='%Y%m%d', errors='coerce')
    mask2 = result.isna()
    if mask2.any():
        result.loc[mask2] = pd.to_datetime(cleaned.loc[mask2], errors='coerce')
    return result


def compute_ma_cross_signal(s: pd.Series, ma6: pd.Series, ma12: pd.Series) -> pd.Series:
    """均线交叉信号：短均线上穿长均线返回1，下穿返回-1，否则0"""
    signal = pd.Series(0, index=s.index)
    above = ma6 > ma12
    # 上穿: 之前ma6<=ma12, 现在ma6>ma12
    crossover_up = above & (~above.shift(1).fillna(False))
    # 下穿: 之前ma6>=ma12, 现在ma6<ma12
    crossover_down = (~above) & (above.shift(1).fillna(False))
    signal[crossover_up] = 1
    signal[crossover_down] = -1
    return signal


SOURCE_DATA = BASE_DIR / "source_data"

# 文件映射表：将 processed 里的输出关联到 source_data 对应的目标文件名
FILE_MAPPING_TO_SOURCE_DATA = {
    "PE_TTM_日度.csv": "中证800PE.csv",
    "PB_日度.csv": "中证800PB.csv",
    "SHIBOR_1W_日度.csv": "SHIBOR_1W完整序列.csv",
    "DR007偏离度_日度.csv": "DR007合成代理序列.csv",
    "国债收益率10Y_日度.csv": "中国国债收益率.csv",
    "制造业PMI_月度.csv": "制造业PMI.csv",
    "CPI同比_月度.csv": "CPI.csv",
    "PPI同比_月度.csv": "PPI.csv",
    "发电量同比_月度.csv": "全社会用电量_发电量代理.csv",
    "新增开户数_月度.csv": "新增投资者.csv",
    "QVIX_日度.csv": "50ETF_QVIX.csv"
}


def merge_incremental_dataframe(existing_df: pd.DataFrame, new_df: pd.DataFrame, key_cols: list = None) -> pd.DataFrame:
    """
    按 key_cols（默认为 date/日期 相关列）对新旧 DataFrame 执行增量去重合并 (Incremental Merge & Deduplication)。
    新拉取的数据覆盖旧记录 (keep='last')，新增日期记录排序追加到末尾。
    """
    if existing_df is None or existing_df.empty:
        return new_df
    if new_df is None or new_df.empty:
        return existing_df

    existing_df = existing_df.dropna(how="all", axis=1).copy()
    new_df = new_df.dropna(how="all", axis=1).copy()

    possible_keys = ["date", "trade_date", "日期", "发布日期", "stat_month", "月份", "数据日期", "报告日", "统计时间"]
    exist_key = next((c for c in possible_keys if c in existing_df.columns), None)
    new_key = next((c for c in possible_keys if c in new_df.columns), None)
    if exist_key and new_key and exist_key != new_key:
        new_df = new_df.rename(columns={new_key: exist_key})

    # 寻找日期标识列
    if key_cols is None:
        key_cols = [col for col in possible_keys if col in existing_df.columns and col in new_df.columns]

    if not key_cols:
        key_cols = [existing_df.columns[0]]  # 默认使用首列作为主键

    try:
        # 合并新旧 DataFrame
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        # 按主键去重，保留最新抓取的记录 keep='last'
        combined = combined.drop_duplicates(subset=key_cols, keep="last")

        # 尝试按第一个主键列排序
        main_key = key_cols[0]
        combined[main_key] = pd.to_datetime(combined[main_key], errors="coerce")
        combined = combined.dropna(subset=[main_key]).sort_values(main_key).reset_index(drop=True)
        return combined
    except Exception as e:
        print(f"  [WARN] [增量合并过程警示] ({e})，返回新抓取数据集")
        return new_df


def save_processed(df: pd.DataFrame, filename: str, category: str):
    """
    保存处理后的数据到 processed/<category>/ 目录，并同步按增量合并 (Incremental Merge) 模式更新。
    如果 target 文件或对应 source_data 文件存在，则自动追加新抓取的增量行，杜绝覆盖历史长序列。
    """
    folder = PROCESSED / category
    folder.mkdir(parents=True, exist_ok=True)
    filepath = folder / filename

    output_df = df.copy()

    # 1. 增量更新 processed/<category>/<filename>
    if filepath.exists() and not output_df.empty:
        try:
            if filename.endswith(".parquet"):
                old_df = pd.read_parquet(filepath)
            else:
                old_df = pd.read_csv(filepath)
            
            old_rows = len(old_df)
            output_df = merge_incremental_dataframe(old_df, output_df)
            added_rows = len(output_df) - old_rows
            if added_rows > 0:
                print(f"  [OK] [增量合并] {filename}: 原有 {old_rows} 行 -> 追加 {added_rows} 行新增数据 (共计 {len(output_df)} 行)")
        except Exception as e:
            print(f"  [WARN] {filename} 历史读取警示 ({e})，覆盖写入")

    # 落盘 processed 目标文件
    if filename.endswith(".parquet"):
        output_df.to_parquet(filepath, index=False)
    else:
        output_df.to_csv(filepath, index=False, encoding="utf-8-sig")

    print(f"[OK] saved processed: {filepath}")

    # 2. 增量同步至 source_data 目录 (如果存在映射或同名文件)
    source_filename = FILE_MAPPING_TO_SOURCE_DATA.get(filename, filename)
    source_path = SOURCE_DATA / source_filename
    if source_path.exists() and not output_df.empty:
        try:
            old_source_df = pd.read_csv(source_path, encoding="utf-8-sig")
            old_source_rows = len(old_source_df)
            merged_source_df = merge_incremental_dataframe(old_source_df, output_df)
            merged_source_df.to_csv(source_path, index=False, encoding="utf-8-sig")
            added_source_rows = len(merged_source_df) - old_source_rows
            if added_source_rows > 0:
                print(f"  [OK] [source_data 增量同步] {source_filename}: 新增 {added_source_rows} 行数据")
        except Exception as e_src:
            print(f"  [WARN] source_data 增量同步失败 ({source_filename}): {e_src}")

    return filepath


def log_fetch(source: str, status: str, message: str = ""):
    """记录抓取日志"""
    LOGS.mkdir(parents=True, exist_ok=True)
    log_file = LOGS / f"fetch_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.log"
    timestamp = datetime.now(TZ_BEIJING).isoformat()
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] [{source}] [{status}] {message}\n")


# 中国交易日历（简化版，沪深交易所交易日）
def get_china_trading_calendar(start: str = "20050101", end: str = "20260723") -> pd.DatetimeIndex:
    """获取中国A股交易日历（通过AKShare）"""
    try:
        import akshare as ak
        calendar = ak.tool_trade_date_hist_sina()
        calendar["trade_date"] = pd.to_datetime(calendar["trade_date"])
        mask = (calendar["trade_date"] >= start) & (calendar["trade_date"] <= end)
        return pd.DatetimeIndex(calendar.loc[mask, "trade_date"].sort_values())
    except Exception:
        # 回退：生成所有工作日
        dates = pd.date_range(start, end, freq="B")
        return dates


if __name__ == "__main__":
    print(f"数据根目录: {BASE_DIR}")
    print(f"原始数据目录: {RAW}")
    print(f"处理后数据目录: {PROCESSED}")
    for d in [RAW, PROCESSED, METADATA, LOGS]:
        print(f"  {d} 存在: {d.exists()}")
