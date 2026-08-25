# -*- coding: utf-8 -*-
"""
择时六面图：指标计算

原则：
1. 本文件只读取 cleaned_data，不再处理原始文件；
2. 可按研报公开公式计算的指标，输出到 results/indicator_outputs；
3. 数据口径或模型无法完全对齐研报的指标，输出到 results/proxy_outputs；
4. 不用无法验证的代理值冒充原研报指标；
5. 代码按指标顺序平铺，便于逐段阅读和修改。

运行：python 02_指标计算.py
"""

from pathlib import Path
import numpy as np
import pandas as pd
try:
    from statsmodels.tsa.seasonal import STL
except ImportError:
    STL = None


BASE_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CLEAN_DIR = BASE_DIR / "cleaned_data"
RESULT_DIR = BASE_DIR / "results"
EXACT_DIR = RESULT_DIR / "indicator_outputs"
PROXY_DIR = RESULT_DIR / "proxy_outputs"
EXACT_DIR.mkdir(parents=True, exist_ok=True)
PROXY_DIR.mkdir(parents=True, exist_ok=True)


def read_clean(file_name):
    df = pd.read_csv(CLEAN_DIR / file_name, encoding="utf-8-sig")
    for column in df.columns:
        if column == "date" or column.endswith("_date"):
            df[column] = pd.to_datetime(df[column], errors="coerce")
    if "date" in df.columns:
        df = df.sort_values("date").reset_index(drop=True)
    return df


def save_exact(df, file_name):
    df.to_csv(EXACT_DIR / file_name, index=False, encoding="utf-8-sig")


def save_proxy(df, file_name):
    df.to_csv(PROXY_DIR / file_name, index=False, encoding="utf-8-sig")


def expanding_quantile_before_today(series, q, min_periods):
    """只使用前一期及更早数据计算历史分位数，避免当前值参与当前阈值。"""
    return series.expanding(min_periods=min_periods).quantile(q).shift(1)


def rolling_zscore(series, window=1250, min_periods=1000):
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std(ddof=1)
    return (series - mean) / std, mean, std


def realtime_stl_adjusted(series, period=12, min_history=36):
    """
    只使用截至当期的数据递归拟合STL，并返回每次拟合末端的季调值。

    直接对全样本拟合一次STL会让历史季节项使用未来观测。本函数虽然仍是
    代理季调方法，但每个历史时点都不读取之后的数据。
    """
    source = pd.to_numeric(series, errors="coerce").ffill()
    adjusted = pd.Series(np.nan, index=source.index, dtype=float)
    seasonal = pd.Series(np.nan, index=source.index, dtype=float)
    if STL is None:
        # 降级模式：若 statsmodels 不可用，直接返回源数据与零季节性项
        return source, pd.Series(0.0, index=source.index, dtype=float)

    for end in range(min_history - 1, len(source)):
        history = source.iloc[: end + 1]
        if history.isna().any():
            continue
        fitted = STL(history, period=period, robust=True).fit()
        seasonal.iloc[end] = fitted.seasonal.iloc[-1]
        adjusted.iloc[end] = history.iloc[-1] - fitted.seasonal.iloc[-1]
    return adjusted, seasonal


def wilder_rsi(close, n):
    """Wilder RSI。"""
    change = close.diff()
    gain = change.clip(lower=0)
    loss = -change.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi[(avg_loss == 0) & (avg_gain > 0)] = 100
    rsi[(avg_gain == 0) & (avg_loss > 0)] = 0
    return rsi


import os

market_calendar_base = read_clean("中证800日行情_清洗后.csv")
MARKET_DATES = pd.DatetimeIndex(
    market_calendar_base["date"].dropna().drop_duplicates().sort_values()
)
TIMING_AS_OF_ENV = os.environ.get("TIMING_AS_OF")
if TIMING_AS_OF_ENV:
    AS_OF_DATE = pd.to_datetime(TIMING_AS_OF_ENV)
else:
    AS_OF_DATE = MARKET_DATES.max()


def next_trading_day(date_series):
    """把信息可用日映射到严格晚于该日的下一交易日。"""
    values = pd.to_datetime(date_series, errors="coerce")
    output = []
    for value in values:
        if pd.isna(value):
            output.append(pd.NaT)
            continue
        position = MARKET_DATES.searchsorted(value, side="right")
        if position < len(MARKET_DATES):
            output.append(MARKET_DATES[position])
        else:
            output.append(value + pd.offsets.BDay(1))
    return pd.to_datetime(output)


def add_effective_date(df, available_col="date"):
    """保留观测日，并补充可用于无前视回测的下一交易日生效日期。"""
    df["effective_date"] = next_trading_day(df[available_col])
    return df


latest_rows = []


def add_latest(
    dimension,
    indicator,
    df,
    value_col,
    score_col,
    text_col,
    level,
    note="",
    aggregation_eligible=None,
):
    valid = df.dropna(subset=[value_col]) if value_col in df.columns else df.copy()
    if "effective_date" in valid.columns:
        # “最新”只取截至统一截面已经生效的记录。
        valid = valid[
            valid["effective_date"].notna()
            & (valid["effective_date"] <= AS_OF_DATE)
        ]
    if len(valid) == 0:
        latest_rows.append({
            "dimension": dimension,
            "indicator": indicator,
            "as_of_date": AS_OF_DATE.strftime("%Y-%m-%d"),
            "latest_date": "",
            "effective_date": "",
            "latest_value": np.nan,
            "signal_score": np.nan,
            "usable_current_score": np.nan,
            "signal_text": "不可计算",
            "replication_level": level,
            "data_age_days": np.nan,
            "is_stale": True,
            "aggregation_eligible": False,
            "note": note,
        })
        return
    row = valid.iloc[-1]
    effective_date = row.get("effective_date", row.get("date", pd.NaT))
    effective_date = pd.to_datetime(effective_date, errors="coerce")
    date_diffs = valid["date"].dropna().sort_values().diff().dt.days.dropna()
    median_gap = date_diffs.median() if len(date_diffs) else np.nan
    if pd.isna(median_gap):
        max_age_days = 180
    elif median_gap <= 7:
        max_age_days = 10
    elif median_gap <= 45:
        max_age_days = 75
    else:
        max_age_days = 180
    data_age_days = (
        int((AS_OF_DATE - effective_date).days)
        if pd.notna(effective_date)
        else np.nan
    )
    is_stale = pd.isna(data_age_days) or data_age_days > max_age_days
    if aggregation_eligible is None:
        aggregation_eligible = level in {
            "可按公开规则复现",
            "可按图表公开参数复现",
            "可复现；GDP发布日期采用保守近似",
        }
    score = row[score_col] if score_col in row else np.nan
    usable_current_score = (
        score if aggregation_eligible and not is_stale else np.nan
    )
    latest_rows.append({
        "dimension": dimension,
        "indicator": indicator,
        "as_of_date": AS_OF_DATE.strftime("%Y-%m-%d"),
        "latest_date": row["date"].strftime("%Y-%m-%d") if "date" in row and pd.notna(row["date"]) else "",
        "effective_date": effective_date.strftime("%Y-%m-%d") if pd.notna(effective_date) else "",
        "latest_value": row[value_col] if value_col in row else np.nan,
        "signal_score": score,
        "usable_current_score": usable_current_score,
        "signal_text": row[text_col] if text_col in row else "",
        "replication_level": level,
        "data_age_days": data_age_days,
        "is_stale": bool(is_stale),
        "aggregation_eligible": bool(aggregation_eligible),
        "note": note,
    })


# ============================================================
# 一、流动性
# ============================================================

# ------------------------------------------------------------
# 1. SHIBOR 1W：MA60低于历史10%分位数时看多
# ------------------------------------------------------------
shibor = read_clean("SHIBOR_1W_清洗后.csv")
shibor["ma60"] = shibor["shibor_1w_pct"].rolling(60, min_periods=60).mean()
shibor["historical_q10"] = expanding_quantile_before_today(shibor["ma60"], 0.10, 250)
shibor["signal_score"] = 0
shibor.loc[shibor["ma60"] < shibor["historical_q10"], "signal_score"] = 1
shibor["signal_text"] = np.where(shibor["signal_score"] == 1, "看多：短端资金处于历史低位", "中性")
shibor["new_bull_trigger"] = (
    (shibor["ma60"] < shibor["historical_q10"])
    & ~(shibor["ma60"].shift(1) < shibor["historical_q10"].shift(1)).fillna(False)
)
shibor = add_effective_date(shibor)
save_exact(shibor, "01_SHIBOR_1W信号_日度.csv")
add_latest("流动性", "SHIBOR 1W", shibor, "ma60", "signal_score", "signal_text", "可按公开规则复现")


# ------------------------------------------------------------
# 2. DR007水平代理
# 压缩包缺少央行7天逆回购利率，不能计算原报告的DR007偏离度。
# 这里只对已有合成DR007水平做MA60与历史10%分位判断。
# ------------------------------------------------------------
dr007 = read_clean("DR007水平代理_清洗后.csv")
dr007["ma60"] = dr007["dr007"].rolling(60, min_periods=60).mean()
dr007["historical_q10"] = expanding_quantile_before_today(dr007["ma60"], 0.10, 250)
dr007["signal_score"] = 0
dr007.loc[dr007["ma60"] < dr007["historical_q10"], "signal_score"] = 1
dr007["signal_text"] = np.where(dr007["signal_score"] == 1, "代理看多：DR007水平处于历史低位", "代理中性")
dr007["independent_from_shibor"] = False
dr007 = add_effective_date(dr007)
save_proxy(dr007, "P01_DR007水平代理_日度.csv")
add_latest(
    "流动性", "DR007偏离度", dr007, "ma60", "signal_score", "signal_text", "代理",
    "缺少7天逆回购利率历史序列；2022年前序列是SHIBOR加固定利差，不独立、不得与SHIBOR重复计分。",
    aggregation_eligible=False,
)


# ------------------------------------------------------------
# 3. M1同比：MA6与MA12判断趋势
# ------------------------------------------------------------
money = read_clean("货币供应量_清洗后.csv")
m1 = money[["date", "available_date", "m1_yoy_pct"]].copy()
m1["ma6"] = m1["m1_yoy_pct"].rolling(6, min_periods=6).mean()
m1["ma12"] = m1["m1_yoy_pct"].rolling(12, min_periods=12).mean()
m1["signal_score"] = np.nan
m1.loc[m1["ma6"] > m1["ma12"], "signal_score"] = 1
m1.loc[m1["ma6"] < m1["ma12"], "signal_score"] = -1
m1["signal_text"] = "样本不足"
m1.loc[m1["signal_score"] == 1, "signal_text"] = "看多：M1同比上行"
m1.loc[m1["signal_score"] == -1, "signal_text"] = "看空：M1同比下行"
m1 = add_effective_date(m1, "available_date")
save_exact(m1, "02_M1同比趋势_月度.csv")
add_latest("流动性", "M1同比", m1, "m1_yoy_pct", "signal_score", "signal_text", "可按公开规则复现")


# ------------------------------------------------------------
# 4. M1同比-PPI同比：MA6与MA12判断趋势
# ------------------------------------------------------------
prices = read_clean("CPI_PPI_清洗后.csv")
m1_ppi = pd.merge(
    money[["date", "available_date", "m1_yoy_pct"]],
    prices[["date", "ppi_available_date", "ppi_yoy_pct"]],
    on="date",
    how="inner",
)
m1_ppi["signal_available_date"] = m1_ppi[
    ["available_date", "ppi_available_date"]
].max(axis=1)
m1_ppi["m1_minus_ppi_pct_point"] = m1_ppi["m1_yoy_pct"] - m1_ppi["ppi_yoy_pct"]
m1_ppi["ma6"] = m1_ppi["m1_minus_ppi_pct_point"].rolling(6, min_periods=6).mean()
m1_ppi["ma12"] = m1_ppi["m1_minus_ppi_pct_point"].rolling(12, min_periods=12).mean()
m1_ppi["signal_score"] = np.nan
m1_ppi.loc[m1_ppi["ma6"] > m1_ppi["ma12"], "signal_score"] = 1
m1_ppi.loc[m1_ppi["ma6"] < m1_ppi["ma12"], "signal_score"] = -1
m1_ppi["signal_text"] = "样本不足"
m1_ppi.loc[m1_ppi["signal_score"] == 1, "signal_text"] = "看多：剪刀差上行"
m1_ppi.loc[m1_ppi["signal_score"] == -1, "signal_text"] = "看空：剪刀差下行"
m1_ppi = add_effective_date(m1_ppi, "signal_available_date")
save_exact(m1_ppi, "03_M1减PPI趋势_月度.csv")
add_latest("流动性", "M1同比-PPI同比", m1_ppi, "m1_minus_ppi_pct_point", "signal_score", "signal_text", "可按公开规则复现")


# ------------------------------------------------------------
# 5. M2同比-名义GDP累计同比
# GDP按保守可用日期映射到月度，避免把季度数据提前使用。
# ------------------------------------------------------------
gdp = read_clean("名义GDP_清洗后.csv")
gdp["conservative_available_date"] = pd.to_datetime(gdp["conservative_available_date"])
gdp_available = gdp[[
    "conservative_available_date", "date", "nominal_gdp_cum_yoy_pct"
]].rename(columns={"date": "gdp_stat_period_end"}).dropna(subset=["nominal_gdp_cum_yoy_pct"])
gdp_available = gdp_available.sort_values("conservative_available_date")

m2_available = money[
    ["date", "available_date", "m2_yoy_pct"]
].rename(columns={"date": "m2_stat_period_end"}).sort_values("available_date")
release_events = pd.DataFrame({
    "signal_available_date": pd.concat([
        m2_available["available_date"],
        gdp_available["conservative_available_date"],
    ]).dropna().drop_duplicates().sort_values()
})
m2_gdp = pd.merge_asof(
    release_events,
    m2_available,
    left_on="signal_available_date",
    right_on="available_date",
    direction="backward",
)
m2_gdp = pd.merge_asof(
    m2_gdp.sort_values("signal_available_date"),
    gdp_available,
    left_on="signal_available_date",
    right_on="conservative_available_date",
    direction="backward",
)
m2_gdp["date"] = m2_gdp["signal_available_date"]
m2_gdp["m2_minus_nominal_gdp_pct_point"] = m2_gdp["m2_yoy_pct"] - m2_gdp["nominal_gdp_cum_yoy_pct"]
m2_gdp["signal_score"] = np.nan
m2_gdp.loc[m2_gdp["m2_minus_nominal_gdp_pct_point"] > 0, "signal_score"] = 1
m2_gdp.loc[m2_gdp["m2_minus_nominal_gdp_pct_point"] < 0, "signal_score"] = -1
m2_gdp["signal_text"] = "样本不足"
m2_gdp.loc[m2_gdp["signal_score"] == 1, "signal_text"] = "看多：M2增速高于名义GDP增速"
m2_gdp.loc[m2_gdp["signal_score"] == -1, "signal_text"] = "看空：M2增速低于名义GDP增速"
m2_gdp = add_effective_date(m2_gdp, "signal_available_date")
save_exact(m2_gdp, "04_M2减名义GDP_月度.csv")
add_latest("流动性", "M2同比-名义GDP增速", m2_gdp, "m2_minus_nominal_gdp_pct_point", "signal_score", "signal_text", "可复现；GDP发布日期采用保守近似")


# ------------------------------------------------------------
# 6. 信贷脉冲：社融增量经STL季调后计算环比
# 原研报未披露季调程序；STL是透明代理，不声称与Wind季调完全一致。
# ------------------------------------------------------------
sf = read_clean("社会融资规模增量_清洗后.csv")
full_months = pd.date_range(sf["date"].min(), sf["date"].max(), freq="ME")
sf = sf.set_index("date").reindex(full_months).rename_axis("date").reset_index()

# 缺口只允许使用此前数据前向填充。每个历史时点单独递归拟合，
# 避免全样本STL和双向插值把未来月份带入历史信号。
sf["sf_for_stl"] = sf["social_financing_100m"].ffill()
(
    sf["social_financing_sa_100m"],
    sf["seasonal_component"],
) = realtime_stl_adjusted(sf["sf_for_stl"], period=12, min_history=36)

previous_sa = sf["social_financing_sa_100m"].shift(1)
valid_ratio = (sf["social_financing_sa_100m"] > 0) & (previous_sa > 0)
sf["sa_mom_pct"] = np.nan
sf.loc[valid_ratio, "sa_mom_pct"] = (
    sf.loc[valid_ratio, "social_financing_sa_100m"]
    / previous_sa.loc[valid_ratio]
    - 1
) * 100
sf["signal_score"] = 0
sf.loc[sf["sa_mom_pct"] > 5, "signal_score"] = 1
sf["signal_text"] = np.where(
    sf["signal_score"] == 1,
    "看多事件：实时递归季调社融环比超过5%",
    "未触发",
)
fallback_available_date = (
    sf["date"] + pd.offsets.MonthBegin(1) + pd.to_timedelta(19, unit="D")
)
sf["available_date"] = sf["available_date"].fillna(fallback_available_date)
sf = add_effective_date(sf, "available_date")
save_proxy(sf, "P02_信贷脉冲_STL季调代理_月度.csv")
add_latest(
    "流动性", "信贷脉冲", sf, "sa_mom_pct", "signal_score", "signal_text", "代理",
    "原研报季调方法未披露；本实现按每个历史时点递归拟合STL，不使用未来月份。",
    aggregation_eligible=False,
)


# ============================================================
# 二、经济面
# ============================================================

# ------------------------------------------------------------
# 7. 制造业PMI
# ------------------------------------------------------------
pmi = read_clean("制造业PMI_清洗后.csv")
pmi["ma6"] = pmi["manufacturing_pmi"].rolling(6, min_periods=6).mean()
pmi["ma12"] = pmi["manufacturing_pmi"].rolling(12, min_periods=12).mean()
pmi["signal_score"] = np.nan
pmi.loc[pmi["ma6"] > pmi["ma12"], "signal_score"] = 1
pmi.loc[pmi["ma6"] < pmi["ma12"], "signal_score"] = -1
pmi["signal_text"] = "样本不足"
pmi.loc[pmi["signal_score"] == 1, "signal_text"] = "看多：PMI趋势上行"
pmi.loc[pmi["signal_score"] == -1, "signal_text"] = "看空：PMI趋势下行"
pmi = add_effective_date(pmi, "available_date")
save_exact(pmi, "05_制造业PMI趋势_月度.csv")
add_latest("经济面", "制造业PMI", pmi, "manufacturing_pmi", "signal_score", "signal_text", "可按公开规则复现")


# ------------------------------------------------------------
# 8. 全社会用电量同比代理
# 数据不是研报所述“规模以上工业发电量同比”，仅单独输出代理结果。
# ------------------------------------------------------------
electricity = read_clean("全社会用电量同比_代理_清洗后.csv")
electricity["ma6"] = electricity["electricity_consumption_yoy_pct"].rolling(6, min_periods=6).mean()
electricity["ma12"] = electricity["electricity_consumption_yoy_pct"].rolling(12, min_periods=12).mean()
electricity["signal_score"] = np.nan
electricity.loc[electricity["ma6"] > electricity["ma12"], "signal_score"] = 1
electricity.loc[electricity["ma6"] < electricity["ma12"], "signal_score"] = -1
electricity["signal_text"] = "样本不足"
electricity.loc[electricity["signal_score"] == 1, "signal_text"] = "代理看多：用电量趋势上行"
electricity.loc[electricity["signal_score"] == -1, "signal_text"] = "代理看空：用电量趋势下行"
electricity = add_effective_date(electricity, "available_date")
save_proxy(electricity, "P03_全社会用电量同比趋势代理_月度.csv")
add_latest(
    "经济面", "发电量同比", electricity, "electricity_consumption_yoy_pct", "signal_score", "signal_text", "代理",
    "压缩包提供的是全社会用电量，不是研报的发电量同比。",
)


# ------------------------------------------------------------
# 9. 通胀方向因子：0.5 * CPI同比(MA3) + 0.5 * PPI同比
# 判断逻辑：较3个月前下行 -> 通胀回落、货币宽松空间打开 -> 看多(+1)；否则 看空(-1)
# ------------------------------------------------------------
inflation = prices[["date", "cpi_available_date", "ppi_available_date", "cpi_yoy_pct", "ppi_yoy_pct"]].dropna(subset=["cpi_yoy_pct", "ppi_yoy_pct"]).copy()
inflation["cpi_ma3"] = inflation["cpi_yoy_pct"].rolling(3, min_periods=1).mean()
inflation["inflation_dir_factor"] = 0.5 * inflation["cpi_ma3"] + 0.5 * inflation["ppi_yoy_pct"]
inflation["signal_available_date"] = inflation[["cpi_available_date", "ppi_available_date"]].max(axis=1)

inflation["signal_score"] = np.nan
dir_diff = inflation["inflation_dir_factor"] - inflation["inflation_dir_factor"].shift(3)
inflation.loc[dir_diff < 0, "signal_score"] = 1
inflation.loc[dir_diff >= 0, "signal_score"] = -1
inflation["signal_text"] = "样本不足"
inflation.loc[inflation["signal_score"] == 1, "signal_text"] = "看多：通胀方向因子较3个月前下行"
inflation.loc[inflation["signal_score"] == -1, "signal_text"] = "看空：通胀方向因子较3个月前上行"
inflation = add_effective_date(inflation, "signal_available_date")
save_exact(inflation, "06_通胀方向因子信号_月度.csv")
add_latest("经济面", "通胀方向因子", inflation, "inflation_dir_factor", "signal_score", "signal_text", "可按公开规则复现")


# ------------------------------------------------------------
# 10. 通胀强度因子：衡量通胀显著超预期/不及预期的强度冲击
# 预期差 err = 同比 - 近6个月均值 (EXPECTATION_WINDOW = 6)
# 超预期 zscore = err / 预期差近12个月σ (SURPRISE_STD_WINDOW = 12, ddof=1)
# 通胀强度因子 = mean(CPI超预期z, PPI超预期z)
# 信号：因子 < -1.5σ -> 看多(+1)；> +1.5σ -> 看空(-1)；触发后未来60个交易日有效
# ------------------------------------------------------------
inf_surprise = prices[["date", "cpi_available_date", "ppi_available_date", "cpi_yoy_pct", "ppi_yoy_pct"]].dropna(subset=["cpi_yoy_pct", "ppi_yoy_pct"]).copy()
inf_surprise["signal_available_date"] = inf_surprise[["cpi_available_date", "ppi_available_date"]].max(axis=1)

cpi_exp = inf_surprise["cpi_yoy_pct"].rolling(6, min_periods=3).mean().shift(1)
ppi_exp = inf_surprise["ppi_yoy_pct"].rolling(6, min_periods=3).mean().shift(1)
cpi_err = inf_surprise["cpi_yoy_pct"] - cpi_exp
ppi_err = inf_surprise["ppi_yoy_pct"] - ppi_exp

cpi_err_std = cpi_err.rolling(12, min_periods=6).std(ddof=1)
ppi_err_std = ppi_err.rolling(12, min_periods=6).std(ddof=1)

inf_surprise["cpi_surprise_z"] = cpi_err / cpi_err_std
inf_surprise["ppi_surprise_z"] = ppi_err / ppi_err_std
inf_surprise["inflation_surprise_factor"] = (inf_surprise["cpi_surprise_z"] + inf_surprise["ppi_surprise_z"]) / 2.0

inf_surprise["signal_score"] = 0
inf_surprise.loc[inf_surprise["inflation_surprise_factor"] < -1.5, "signal_score"] = 1
inf_surprise.loc[inf_surprise["inflation_surprise_factor"] > 1.5, "signal_score"] = -1
inf_surprise["signal_text"] = "中性"
inf_surprise.loc[inf_surprise["signal_score"] == 1, "signal_text"] = "看多：通胀显著不及预期"
inf_surprise.loc[inf_surprise["signal_score"] == -1, "signal_text"] = "看空：通胀显著超预期"
inf_surprise = add_effective_date(inf_surprise, "signal_available_date")
save_exact(inf_surprise, "07_通胀强度因子信号_月度.csv")
add_latest("经济面", "通胀强度因子", inf_surprise, "inflation_surprise_factor", "signal_score", "signal_text", "可按公开规则复现")


# 注：原报告中的库存周期、A股景气度指数因公开数据源与Nowcasting模型参数缺失，已按规范剔除。


# ============================================================
# 三、估值面
# ============================================================
valuation = read_clean("中证800_PE_PB_清洗后.csv")
csi_price = market_calendar_base[["date", "close"]].rename(columns={"close": "market_close"}).dropna().sort_values("date")
valuation = pd.merge(valuation, csi_price, on="date", how="left")
if "index_close" in valuation.columns:
    valuation["index_close"] = valuation["index_close"].fillna(valuation["market_close"]).ffill()
else:
    valuation["index_close"] = valuation["market_close"].ffill()
valuation.drop(columns=["market_close"], inplace=True, errors="ignore")

# ------------------------------------------------------------
# 11. 中证800成分股PE_TTM中位数：20倍以下看多
# ------------------------------------------------------------
pe_median = valuation[["date", "pe_ttm_median"]].dropna().copy()
pe_median["bottom_threshold"] = 20.0
pe_median["signal_score"] = np.where(pe_median["pe_ttm_median"] <= 20.0, 1, 0)
pe_median["signal_text"] = np.where(pe_median["signal_score"] == 1, "看多：PE_TTM中位数进入20倍底部区", "中性")
pe_median = add_effective_date(pe_median)
save_exact(pe_median, "08_PE_TTM中位数信号_日度.csv")
add_latest(
    "估值面",
    "中证800成分股PE_TTM中位数",
    pe_median,
    "pe_ttm_median",
    "signal_score",
    "signal_text",
    "阈值公开；接近阈值缓冲未披露",
    "研报在20.43倍时仍按'接近20倍'看多，机械缓冲区未披露。",
    aggregation_eligible=False,
)


# 注：原报告中的中证800股息率因历史序列不全，已按规范剔除。


# ------------------------------------------------------------
# 13. 中证800 PB：1.4倍以下看多
# ------------------------------------------------------------
pb = valuation[["date", "pb_index"]].dropna().copy()
pb["bottom_threshold"] = 1.4
pb["signal_score"] = np.where(pb["pb_index"] <= 1.4, 1, 0)
pb["signal_text"] = np.where(pb["signal_score"] == 1, "看多：PB进入1.4倍底部区", "中性")
pb = add_effective_date(pb)
save_exact(pb, "09_PB信号_日度.csv")
add_latest(
    "估值面",
    "中证800 PB",
    pb,
    "pb_index",
    "signal_score",
    "signal_text",
    "阈值公开；接近阈值缓冲未披露",
    "研报在1.5倍时仍按'接近1.4倍'看多，机械缓冲区未披露。",
    aggregation_eligible=False,
)


# ------------------------------------------------------------
# 14. 席勒 ERP (Shiller CAPE)：过去6年盈利通胀调整后计算席勒ERP
# E_t = P_t / PE_t
# 席勒PE_t = P_t / ( cpi_known[t] * rolling_mean(E_i / cpi_known[i], 1500) )
# 席勒ERP_t = 1/席勒PE_t - 10Y国债到期收益率
# 信号：6年(1500交易日)滚动 Z-score，±1.5σ -> 看多/看空
# ------------------------------------------------------------
bond = read_clean("10年期国债收益率_清洗后.csv")
erp = valuation[["date", "index_close", "pe_ttm_index"]].dropna().sort_values("date").copy()
erp = pd.merge_asof(
    erp,
    bond[["date", "bond_yield_10y_pct"]].sort_values("date"),
    on="date",
    direction="backward",
)

# 引入 CPI 构造定基价格指数（以最早 CPI 为 100）
cpi_data = prices[["date", "cpi_available_date", "cpi_yoy_pct"]].dropna().sort_values("cpi_available_date").copy()
cpi_data["cpi_index"] = (1.0 + cpi_data["cpi_yoy_pct"] / 100.0).cumprod() * 100.0
erp = pd.merge_asof(
    erp,
    cpi_data[["cpi_available_date", "cpi_index"]],
    left_on="date",
    right_on="cpi_available_date",
    direction="backward"
)
erp["cpi_index"] = erp["cpi_index"].ffill().fillna(100.0)

# 反推每股盈利 E = P / PE
erp["earnings"] = erp["index_close"] / erp["pe_ttm_index"]
# 通胀调整后真实盈利 real_E = earnings / cpi_index
erp["real_earnings"] = erp["earnings"] / erp["cpi_index"]
# 6年(1500交易日)滚动平滑真实盈利
erp["rolling_real_e_6y"] = erp["real_earnings"].rolling(1500, min_periods=500).mean()
# 席勒 PE = P / (cpi_index * rolling_real_e_6y)
erp["shiller_pe"] = erp["index_close"] / (erp["cpi_index"] * erp["rolling_real_e_6y"])
# 席勒 ERP = 1 / 席勒PE - 10Y国债收益率
erp["shiller_erp"] = (1.0 / erp["shiller_pe"]) - (erp["bond_yield_10y_pct"] / 100.0)
erp["shiller_erp_pct"] = erp["shiller_erp"] * 100.0

# 6年(1500交易日)滚动 Z-score
erp["erp_z5y"], erp["erp_mean6y"], erp["erp_std6y"] = rolling_zscore(erp["shiller_erp_pct"], 1500, 500)
erp["signal_score"] = 0
erp.loc[erp["erp_z5y"] > 1.5, "signal_score"] = 1
erp.loc[erp["erp_z5y"] < -1.5, "signal_score"] = -1
erp["signal_text"] = "中性"
erp.loc[erp["signal_score"] == 1, "signal_text"] = "看多：席勒ERP高于1.5个标准差"
erp.loc[erp["signal_score"] == -1, "signal_text"] = "看空：席勒ERP低于-1.5个标准差"
erp = add_effective_date(erp)
save_exact(erp, "10_股权风险溢价_日度.csv")
add_latest("估值面", "中证800席勒ERP", erp, "shiller_erp_pct", "signal_score", "signal_text", "可按公开规则复现")


# 注：原报告中的DCF和AIAE因模型参数与数据口径缺失，已按规范剔除。


# ============================================================
# 四、资金面
# ============================================================

# 注：原报告中的新增开户数因统计数据停更且方向未披露，已按规范剔除。


# 北向资金指标已移除（数据源不可用），north 变量设为 None
north = None


# ------------------------------------------------------------
# 17. 两融增量：对净两融额日增量做长窗口趋势判断 (MA120 vs MA240)
# margin_net = 融资余额 - 融券余额
# net_delta = margin_net.diff()
# signal = +1 if net_delta_ma120 > net_delta_ma240 else -1
# ------------------------------------------------------------
margin = read_clean("融资融券余额_清洗后.csv")
if "margin_net" not in margin.columns:
    margin["margin_net"] = margin["margin_total"]
margin["net_delta"] = margin["margin_net"].diff()
margin["net_delta_ma120"] = margin["net_delta"].rolling(120, min_periods=60).mean()
margin["net_delta_ma240"] = margin["net_delta"].rolling(240, min_periods=120).mean()
margin["signal_score"] = np.nan
margin.loc[margin["net_delta_ma120"] > margin["net_delta_ma240"], "signal_score"] = 1
margin.loc[margin["net_delta_ma120"] < margin["net_delta_ma240"], "signal_score"] = -1
margin["signal_text"] = "样本不足"
margin.loc[margin["signal_score"] == 1, "signal_text"] = "代理看多：两融增量提速(MA120>MA240)"
margin.loc[margin["signal_score"] == -1, "signal_text"] = "代理看空：两融增量放缓(MA120<MA240)"
margin = add_effective_date(margin)
save_proxy(margin, "P05_两融增量_MA120_MA240_日度.csv")
add_latest(
    "资金面", "两融增量", margin, "net_delta_ma120", "signal_score", "signal_text", "透明代理",
    "采用120日与240日净两融额日增量均线判断边际杠杆资金提速与放缓。",
)


# ============================================================
# 五、技术面
# ============================================================
market = market_calendar_base.copy()

# ------------------------------------------------------------
# 18. 均线排列：MA10 > MA30 > MA60时看多
# ------------------------------------------------------------
ma_align = market[["date", "close"]].copy()
ma_align["ma10"] = ma_align["close"].rolling(10, min_periods=10).mean()
ma_align["ma30"] = ma_align["close"].rolling(30, min_periods=30).mean()
ma_align["ma60"] = ma_align["close"].rolling(60, min_periods=60).mean()
ma_align["bull_alignment"] = (ma_align["ma10"] > ma_align["ma30"]) & (ma_align["ma30"] > ma_align["ma60"])
ma_align["bear_alignment_supplement"] = (ma_align["ma10"] < ma_align["ma30"]) & (ma_align["ma30"] < ma_align["ma60"])
ma_align["signal_score"] = np.where(ma_align["bull_alignment"], 1, 0)
ma_align["signal_text"] = np.where(ma_align["bull_alignment"], "看多：10/30/60日均线多头排列", "未触发多头排列")
ma_align = add_effective_date(ma_align)
save_exact(ma_align, "13_均线排列_日度.csv")
add_latest("技术面", "均线排列", ma_align, "close", "signal_score", "signal_text", "可按图表公开参数复现")


# ------------------------------------------------------------
# 19. 均线距离：MA10/MA60-1，超过±3%判断趋势
# 均线长度未在正文披露，采用压缩包已有的10/60日设定。
# ------------------------------------------------------------
ma_distance = market[["date", "close"]].copy()
ma_distance["ma10"] = ma_distance["close"].rolling(10, min_periods=10).mean()
ma_distance["ma60"] = ma_distance["close"].rolling(60, min_periods=60).mean()
ma_distance["distance_pct"] = (ma_distance["ma10"] / ma_distance["ma60"] - 1) * 100
ma_distance["signal_score"] = 0
ma_distance.loc[ma_distance["distance_pct"] > 3, "signal_score"] = 1
ma_distance.loc[ma_distance["distance_pct"] < -3, "signal_score"] = -1
ma_distance["signal_text"] = "震荡"
ma_distance.loc[ma_distance["signal_score"] == 1, "signal_text"] = "看多：短均线高于长均线3%以上"
ma_distance.loc[ma_distance["signal_score"] == -1, "signal_text"] = "看空：短均线低于长均线3%以上"
ma_distance = add_effective_date(ma_distance)
save_proxy(ma_distance, "P06_均线距离_MA10_MA60_日度.csv")
add_latest(
    "技术面", "均线距离", ma_distance, "distance_pct", "signal_score", "signal_text", "参数假设",
    "研报公开±3%阈值，但未写明长短均线天数；采用数据包的MA10/MA60。",
)


# ------------------------------------------------------------
# 20. 布林带：上穿上轨后重新跌回上轨内做空；下穿下轨后重新回到下轨上方做多
# ------------------------------------------------------------
boll = market[["date", "close"]].copy()
boll["middle"] = boll["close"].rolling(20, min_periods=20).mean()
boll["std20"] = boll["close"].rolling(20, min_periods=20).std(ddof=0)
boll["upper"] = boll["middle"] + 2 * boll["std20"]
boll["lower"] = boll["middle"] - 2 * boll["std20"]
boll["trigger"] = ""
short_trigger = (boll["close"].shift(1) > boll["upper"].shift(1)) & (boll["close"] <= boll["upper"])
long_trigger = (boll["close"].shift(1) < boll["lower"].shift(1)) & (boll["close"] >= boll["lower"])
boll.loc[short_trigger, "trigger"] = "看空触发"
boll.loc[long_trigger, "trigger"] = "看多触发"

# 研报在指数位于通道中部时写“不发出信号”，因此主信号只记录触发日。
boll["signal_score"] = 0
boll.loc[boll["trigger"] == "看多触发", "signal_score"] = 1
boll.loc[boll["trigger"] == "看空触发", "signal_score"] = -1
boll["signal_text"] = "中性：当前未触发"
boll.loc[boll["signal_score"] == 1, "signal_text"] = "看多触发：下穿下轨后重新上穿下轨"
boll.loc[boll["signal_score"] == -1, "signal_text"] = "看空触发：上穿上轨后重新下穿上轨"

# 补充保留最近一次触发方向，但不把它当作原报告的当前信号。
state = 0
states = []
for trigger in boll["trigger"]:
    if trigger == "看多触发":
        state = 1
    elif trigger == "看空触发":
        state = -1
    states.append(state)
boll["last_trigger_state_supplement"] = states

boll = add_effective_date(boll)
save_proxy(boll, "P13_布林带触发信号_MA20_2σ_日度.csv")
add_latest(
    "技术面",
    "布林带",
    boll,
    "close",
    "signal_score",
    "signal_text",
    "参数假设",
    "触发逻辑公开，但研报未披露窗口和倍数；采用MA20±2σ。",
    aggregation_eligible=False,
)


# ------------------------------------------------------------
# 21. RSI：RSI6快线、RSI24慢线，20/80为触发区
# ------------------------------------------------------------
rsi = market[["date", "close"]].copy()
rsi["rsi6"] = wilder_rsi(rsi["close"], 6)
rsi["rsi24"] = wilder_rsi(rsi["close"], 24)
rsi["trigger"] = ""

armed_long = False
armed_short = False
state = 0
states = []
triggers = []
for i in range(len(rsi)):
    fast = rsi.loc[i, "rsi6"]
    slow = rsi.loc[i, "rsi24"]
    previous_fast = rsi.loc[i - 1, "rsi6"] if i > 0 else np.nan
    previous_slow = rsi.loc[i - 1, "rsi24"] if i > 0 else np.nan
    trigger = ""

    if pd.notna(fast) and fast < 20:
        armed_long = True
    if pd.notna(fast) and fast > 80:
        armed_short = True

    cross_up = i > 0 and pd.notna(previous_fast) and pd.notna(previous_slow) and previous_fast <= previous_slow and fast > slow
    cross_down = i > 0 and pd.notna(previous_fast) and pd.notna(previous_slow) and previous_fast >= previous_slow and fast < slow

    if armed_long and cross_up:
        state = 1
        trigger = "看多触发"
        armed_long = False
        armed_short = False
    elif armed_short and cross_down:
        state = -1
        trigger = "看空触发"
        armed_long = False
        armed_short = False

    triggers.append(trigger)
    states.append(state)

rsi["trigger"] = triggers
rsi["signal_score"] = states
rsi["signal_text"] = rsi["signal_score"].map({1: "看多状态", 0: "中性状态", -1: "看空状态"})
rsi = add_effective_date(rsi)
save_proxy(rsi, "P14_RSI_Wilder状态_日度.csv")
add_latest(
    "技术面",
    "RSI",
    rsi,
    "rsi6",
    "signal_score",
    "signal_text",
    "算法假设",
    "RSI6/24及20/80公开，但平滑算法未披露；采用Wilder算法。",
    aggregation_eligible=False,
)


# ------------------------------------------------------------
# 22. 新高新低占比：压缩包只有15个行业指数代理，不是全市场股票占比
# ------------------------------------------------------------
breadth = read_clean("行业新高新低_代理_清洗后.csv")
breadth["signal_score"] = 0
breadth.loc[(breadth["nh_ratio"] >= 0.10) & (breadth["nl_ratio"] < 0.10), "signal_score"] = -1
breadth.loc[(breadth["nl_ratio"] >= 0.10) & (breadth["nh_ratio"] < 0.10), "signal_score"] = 1
breadth["signal_text"] = "代理中性"
breadth.loc[breadth["signal_score"] == 1, "signal_text"] = "代理看多：行业新低占比达到10%"
breadth.loc[breadth["signal_score"] == -1, "signal_text"] = "代理看空：行业新高占比达到10%"
breadth["nh_signal_score"] = np.where(breadth["nh_ratio"] >= 0.10, -1, 0)
breadth["nh_signal_text"] = np.where(
    breadth["nh_signal_score"] == -1,
    "代理看空：行业新高占比达到10%",
    "代理中性",
)
breadth["nl_signal_score"] = np.where(breadth["nl_ratio"] >= 0.10, 1, 0)
breadth["nl_signal_text"] = np.where(
    breadth["nl_signal_score"] == 1,
    "代理看多：行业新低占比达到10%",
    "代理中性",
)
breadth = add_effective_date(breadth)
save_proxy(breadth, "P07_行业新高新低占比代理_日度.csv")
add_latest(
    "技术面", "250日新高占比", breadth, "nh_ratio", "nh_signal_score", "nh_signal_text", "代理",
    "原研报需要全市场股票；压缩包仅有15个行业指数。",
)
add_latest(
    "技术面", "250日新低占比", breadth, "nl_ratio", "nl_signal_score", "nl_signal_text", "代理",
    "原研报需要全市场股票；压缩包仅有15个行业指数。",
)


# ------------------------------------------------------------
# 23. 成交额+波动率时钟：透明趋势代理
# 成交额趋势：MA20(amount)与MA60(amount)
# 波动率趋势：20日年化波动率的MA20与MA60
# ------------------------------------------------------------
clock = market[["date", "close", "amount"]].copy()
clock["log_return"] = np.log(clock["close"] / clock["close"].shift(1))
clock["volatility_20d_ann"] = clock["log_return"].rolling(20, min_periods=20).std(ddof=1) * np.sqrt(250)
clock["amount_ma20"] = clock["amount"].rolling(20, min_periods=20).mean()
clock["amount_ma60"] = clock["amount"].rolling(60, min_periods=60).mean()
clock["vol_ma20"] = clock["volatility_20d_ann"].rolling(20, min_periods=20).mean()
clock["vol_ma60"] = clock["volatility_20d_ann"].rolling(60, min_periods=60).mean()
clock["amount_trend"] = np.where(clock["amount_ma20"] > clock["amount_ma60"], "成交上", "成交下")
clock["volatility_trend"] = np.where(clock["vol_ma20"] > clock["vol_ma60"], "波动上", "波动下")
clock["quadrant"] = clock["volatility_trend"] + "+" + clock["amount_trend"]
clock["signal_score"] = 1
clock.loc[clock["quadrant"] == "波动上+成交下", "signal_score"] = -1
clock.loc[clock[["amount_ma60", "vol_ma60"]].isna().any(axis=1), "signal_score"] = np.nan
clock["signal_text"] = np.where(clock["signal_score"] == -1, "看空：波动上+成交下", "看多/低风险象限")
clock.loc[clock["signal_score"].isna(), "signal_text"] = "样本不足"
clock = add_effective_date(clock)
save_proxy(clock, "P08_量价时钟透明代理_日度.csv")
add_latest(
    "技术面", "成交额+波动率时钟", clock, "volatility_20d_ann", "signal_score", "signal_text", "透明代理",
    "原研报未披露趋势滤波参数；本实现用20/60日均线判断上下行。",
)


# ============================================================
# 六、情绪面
# ============================================================

# ------------------------------------------------------------
# 24. 成交热度：用中证800成交额替代缺失的沪深300成交额
# ------------------------------------------------------------
heat = market[["date", "close", "amount"]].copy()
heat["heat_3m"] = heat["amount"].rolling(60, min_periods=60).mean()
heat["heat_z5y"], heat["heat_mean5y"], heat["heat_std5y"] = rolling_zscore(heat["heat_3m"], 1250, 1000)
heat["signal_score"] = 0
heat.loc[heat["heat_z5y"] < -1, "signal_score"] = 1
heat.loc[heat["heat_z5y"] > 1, "signal_score"] = -1
heat["signal_text"] = "中性"
heat.loc[heat["signal_score"] == 1, "signal_text"] = "代理看多：成交情绪过冷"
heat.loc[heat["signal_score"] == -1, "signal_text"] = "代理看空：成交情绪过热"
heat = add_effective_date(heat)
save_proxy(heat, "P09_成交热度_中证800成交额代理_日度.csv")
add_latest(
    "情绪面", "成交热度", heat, "heat_z5y", "signal_score", "signal_text", "代理",
    "研报使用沪深300成交金额；压缩包的沪深300数据只有成交量，故改用中证800成交额并单独标注。",
)


# ------------------------------------------------------------
# 25. 行业分歧度代理
# 原研报公式为100%-过去10日行业收益率第一主成分解释比例；
# 压缩包只有另一种分歧度结果，因此只按其自身历史±1σ做反向情绪信号。
# ------------------------------------------------------------
divergence = read_clean("行业分歧度_代理_清洗后.csv")
divergence["divergence_ma20"] = divergence["divergence"].rolling(20, min_periods=20).mean()
divergence["z5y"], divergence["mean5y"], divergence["std5y"] = rolling_zscore(divergence["divergence_ma20"], 1250, 750)
divergence["signal_score"] = 0
divergence.loc[divergence["z5y"] < -1, "signal_score"] = 1
divergence.loc[divergence["z5y"] > 1, "signal_score"] = -1
divergence["signal_text"] = "代理中性"
divergence.loc[divergence["signal_score"] == 1, "signal_text"] = "代理看多：行业分歧较低"
divergence.loc[divergence["signal_score"] == -1, "signal_text"] = "代理看空：行业分歧较高"
divergence = add_effective_date(divergence)
save_proxy(divergence, "P10_行业分歧度代理_日度.csv")
add_latest(
    "情绪面", "行业分歧度", divergence, "z5y", "signal_score", "signal_text", "代理",
    "底层计算不是研报的PCA解释比例，不能视为精确复刻。",
)


# ------------------------------------------------------------
# 26. 基金仓位代理
# 原研报为主动权益基金带约束回归估算；压缩包是全市场基金季度资产配置。
# ------------------------------------------------------------
fund_q = read_clean("全市场基金股票仓位_代理_清洗后.csv")
calendar = market[["date"]].copy()
fund_source = fund_q[
    ["date", "available_date", "all_fund_equity_position_pct", "fund_count"]
].rename(columns={"date": "fund_period_end"}).sort_values("available_date")
fund_daily = pd.merge_asof(
    calendar.sort_values("date"),
    fund_source,
    left_on="date",
    right_on="available_date",
    direction="backward",
)
fund_daily["position_ma5"] = fund_daily["all_fund_equity_position_pct"].rolling(5, min_periods=5).mean()
fund_daily["position_z5y"], fund_daily["position_mean5y"], fund_daily["position_std5y"] = rolling_zscore(fund_daily["position_ma5"], 1250, 750)
fund_daily["signal_score"] = 0
fund_daily.loc[fund_daily["position_z5y"] < -1, "signal_score"] = 1
fund_daily.loc[fund_daily["position_z5y"] > 1, "signal_score"] = -1
fund_daily["signal_text"] = "代理中性"
fund_daily.loc[fund_daily["signal_score"] == 1, "signal_text"] = "代理看多：基金股票仓位偏低"
fund_daily.loc[fund_daily["signal_score"] == -1, "signal_text"] = "代理看空：基金股票仓位偏高"
fund_daily = add_effective_date(fund_daily)
save_proxy(fund_daily, "P11_全市场基金股票仓位代理_日度.csv")
add_latest(
    "情绪面", "偏股基金仓位", fund_daily, "position_z5y", "signal_score", "signal_text", "代理",
    "全市场基金资产配置不等于主动权益基金带约束回归仓位。",
)


# 注：原报告中的东财NLP情绪因缺少历史语料模型，已按规范剔除。


# ------------------------------------------------------------
# 27. 50ETF QVIX：高于均值+1σ时视为恐慌过度，反向看多
# 采用可用全历史滚动 z-score (min_periods=12，透明窗口假设)
# ------------------------------------------------------------
qvix = read_clean("50ETF_QVIX_清洗后.csv")
qvix["qvix_mean"] = qvix["qvix"].expanding(min_periods=12).mean()
qvix["qvix_std"] = qvix["qvix"].expanding(min_periods=12).std(ddof=1)
qvix["qvix_z5y"] = (qvix["qvix"] - qvix["qvix_mean"]) / qvix["qvix_std"]
qvix["signal_score"] = 0
qvix.loc[qvix["qvix_z5y"] > 1, "signal_score"] = 1
qvix["signal_text"] = np.where(qvix["signal_score"] == 1, "看多：期权恐慌处于高位(恐慌过度)", "中性")
qvix = add_effective_date(qvix)
save_proxy(qvix, "P12_50ETF_QVIX信号_日度.csv")
add_latest(
    "情绪面", "50ETF期权VIX", qvix, "qvix_z5y", "signal_score", "signal_text", "窗口假设",
    "QVIX采用全历史滚动 z-score (min_periods=12)，高于+1σ反向看多。",
)


# 注：原报告中的期权CPR、SKEW因成交明细历史与口径问题，已按规范剔除。


# ============================================================
# 七、最新信号汇总与复刻边界
# ============================================================
latest = pd.DataFrame(latest_rows)
for column, default in {
    "as_of_date": AS_OF_DATE.strftime("%Y-%m-%d"),
    "effective_date": "",
    "usable_current_score": np.nan,
    "data_age_days": np.nan,
    "is_stale": True,
    "aggregation_eligible": False,
}.items():
    if column not in latest.columns:
        latest[column] = default
    else:
        latest[column] = latest[column].apply(
            lambda value: default if pd.isna(value) else value
        )
latest = latest[
    [
        "dimension", "indicator", "as_of_date", "latest_date", "effective_date",
        "latest_value", "signal_score", "usable_current_score", "signal_text",
        "replication_level", "data_age_days", "is_stale",
        "aggregation_eligible", "note",
    ]
]
latest.to_csv(RESULT_DIR / "最新信号汇总.csv", index=False, encoding="utf-8-sig")

# 直接增量写入 MongoDB 数据库 ('timing_signals_summary' 集合)
try:
    import asyncio
    from app.db.mongodb import MongoDBClient
    async def _upsert_signals_to_mongo():
        db_client = MongoDBClient.get_instance()
        if await db_client.connect():
            records = latest.to_dict(orient="records")
            count = await db_client.upsert_timing_signals_batch(records)
            await db_client.close()
            print(f"  [OK] 成功将 {count} 项择时六面图计算信号增量落盘至 MongoDB ('timing_signals_summary')！")
    asyncio.run(_upsert_signals_to_mongo())
except Exception as e_mongo:
    print(f"  [WARN] MongoDB 择时信号落盘提示: {e_mongo}")

replication_summary = pd.DataFrame([
    ["可按公开规则复现", "SHIBOR 1W、M1、M1-PPI、M2-名义GDP、PMI、通胀方向因子、通胀强度因子、席勒ERP、均线排列"],
    ["事件可复现但方向未披露", "新增开户数"],
    ["阈值/算法假设", "PE中位数、PB、布林带、RSI"],
    ["透明代理/参数假设", "DR007水平、信贷脉冲、发电量、两融增量、均线距离、量价时钟、成交热度、行业分歧度、基金仓位、QVIX、新高新低占比"],
    ["不能严谨复现", "库存周期、A股景气度、DCF、AIAE、NLP、CPR、期权SKEW；股息率仅有最近20日"],
], columns=["category", "indicators"])
replication_summary.to_csv(RESULT_DIR / "复刻边界汇总.csv", index=False, encoding="utf-8-sig")


# ============================================================
# 八、研报时点复核（2022-07-31）
# ============================================================
# 这里按“截至研报日通常已经公布的统计期”取值，而不是简单取日期不晚于
# 2022-07-31 的所有月度数据。这样可以避免把2022年7月M1、M2、CPI、PPI、
# 社融和用电量等后来才公布的数据提前用于7月31日判断。


def pick_row(df, cutoff):
    """
    按研报发布时已知信息取截面值。

    月度数据优先按保守可用日筛选；日度收盘数据按观测日筛选。effective_date
    用于回测交易执行，不用于周末发布的研报回看（7月29日收盘在7月31日已知）。
    """
    cutoff = pd.Timestamp(cutoff)
    availability_candidates = [
        "signal_available_date",
        "available_date",
        "cpi_available_date",
        "ppi_available_date",
        "conservative_available_date",
    ]
    date_col = next(
        (column for column in availability_candidates if column in df.columns),
        "date",
    )
    dates = pd.to_datetime(df[date_col], errors="coerce")
    temp = df[dates <= cutoff].copy()
    if len(temp) == 0:
        return None
    return temp.iloc[-1]


def simple_direction(score):
    if pd.isna(score):
        return "不可比较"
    if score > 0:
        return "看多"
    if score < 0:
        return "看空"
    return "中性"


review_rows = []


def add_review(indicator, report_value, report_signal, row, value_col, note="", compare=True):
    if row is None:
        review_rows.append({
            "指标": indicator,
            "研报值/状态": report_value,
            "研报信号": report_signal,
            "本实现采用的可用数据期": "",
            "本实现值": np.nan,
            "本实现信号": "不可计算",
            "方向是否一致": np.nan,
            "说明": note,
        })
        return

    score = row.get("signal_score", np.nan)
    implementation_signal = row.get("signal_text", simple_direction(score))
    implementation_direction = simple_direction(score)
    same = (implementation_direction == report_signal) if compare and implementation_direction != "不可比较" else np.nan
    review_rows.append({
        "指标": indicator,
        "研报值/状态": report_value,
        "研报信号": report_signal,
        "本实现采用的可用数据期": row["date"].strftime("%Y-%m-%d") if pd.notna(row.get("date")) else "",
        "本实现值": row.get(value_col, np.nan),
        "本实现信号": implementation_signal,
        "方向是否一致": same,
        "说明": note,
    })


# 所有序列统一使用研报日截面；日度值按下一交易日生效，因此不会使用7月29日收盘后
# 才能形成、8月1日才可执行的信号。月度值按上游保守可用日进入截面。
report_cutoff = "2022-07-31"
add_review("DR007偏离度", "低于10%历史分位", "看多", pick_row(dr007, report_cutoff), "ma60", "仅DR007水平代理，不能验证原偏离度公式", compare=False)
add_review("SHIBOR 1W", "低于10%历史分位", "看多", pick_row(shibor, report_cutoff), "ma60")
add_review("M1同比", "短均线刚上穿长均线", "看多", pick_row(m1, report_cutoff), "m1_yoy_pct", "按保守发布日期，使用研报日前可得的最近一期")
add_review("M1同比-PPI同比", "短均线连续两月高于长均线", "看多", pick_row(m1_ppi, report_cutoff), "m1_minus_ppi_pct_point", "按两项数据中较晚的保守发布日期生效")

add_review(
    "M2同比-名义GDP",
    "大于0",
    "看多",
    pick_row(m2_gdp, report_cutoff),
    "m2_minus_nominal_gdp_pct_point",
    "按M2或GDP任一数据新发布时重算，使用当时已知的两项最新值",
)

add_review("信贷脉冲", "季调环比未超过5%", "中性", pick_row(sf, report_cutoff), "sa_mom_pct", "递归STL仅使用截至当期历史，仍属于季调代理")
add_review("制造业PMI", "尚未明显上行", "看空", pick_row(pmi, report_cutoff), "manufacturing_pmi", "按下一交易日生效口径取研报日前可执行信号")
add_review("发电量同比", "短均线拐头但未确认", "看空", pick_row(electricity, report_cutoff), "electricity_consumption_yoy_pct", "数据为全社会用电量代理，不是规模以上工业发电量")
add_review("通胀方向因子", "下行", "看多", pick_row(inflation, report_cutoff), "inflation_dir_factor", "较3个月前下行，货币政策宽松空间打开")
add_review("通胀强度因子", "中间水平", "中性", pick_row(inf_surprise, report_cutoff), "inflation_surprise_factor", "未触发±1.5σ极端超预期冲击")
add_review("PE_TTM中位数", "20.43倍", "看多", pick_row(pe_median, report_cutoff), "pe_ttm_median", "接近20倍底部区")
add_review("中证800 PB", "1.5倍，接近底部", "看多", pick_row(pb, report_cutoff), "pb_index", "机械规则仅在PB不高于1.4时看多")
add_review("中证800席勒ERP", "1.35倍标准差", "看多", pick_row(erp, report_cutoff), "erp_z5y", "方向可核验，基于CPI链式定基平滑6年盈利")
add_review("两融增量", "上行趋势", "看多", pick_row(margin, report_cutoff), "net_delta_ma120", "采用MA120/MA240净增量趋势判据")
add_review("均线排列", "10日下穿30日，不发信号", "中性", pick_row(ma_align, report_cutoff), "close")
add_review("均线距离", "阈值内", "中性", pick_row(ma_distance, report_cutoff), "distance_pct", "研报未披露均线长度")
add_review("布林带", "中间区域", "中性", pick_row(boll, report_cutoff), "close")
add_review("RSI", "空头状态", "看空", pick_row(rsi, report_cutoff), "rsi6")
add_review("250日新高占比", "低", "中性", pick_row(breadth, report_cutoff), "nh_ratio", "行业代理")
add_review("250日新低占比", "低", "中性", pick_row(breadth, report_cutoff), "nl_ratio", "行业代理")
add_review("成交额+波动率时钟", "波动下、成交下", "看多", pick_row(clock, report_cutoff), "volatility_20d_ann", "趋势滤波参数为透明代理")
add_review("成交热度", "中等位置", "中性", pick_row(heat, report_cutoff), "heat_z5y", "使用中证800成交额代理")
add_review("行业分歧度", "中等位置", "中性", pick_row(divergence, report_cutoff), "z5y", "分歧度指标", compare=False)
add_review("偏股基金仓位", "中等偏高，轻度看跌", "看空", pick_row(fund_daily, report_cutoff), "position_z5y", "全市场基金资产配置代理")
add_review("50ETF期权VIX", "中等位置", "中性", pick_row(qvix, report_cutoff), "qvix_z5y", "采用全历史滚动假设")

# 25 项有效指标复核
review = pd.DataFrame(review_rows)
review.to_csv(RESULT_DIR / "研报2022时点复核.csv", index=False, encoding="utf-8-sig")

print("指标计算完成。")
print(f"严格/近似可复现输出：{EXACT_DIR}")
print(f"代理输出：{PROXY_DIR}")
print(f"最新信号汇总：{RESULT_DIR / '最新信号汇总.csv'}")
print(latest.to_string(index=False))
