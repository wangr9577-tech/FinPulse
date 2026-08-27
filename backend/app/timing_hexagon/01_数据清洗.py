# -*- coding: utf-8 -*-
"""
择时六面图：数据清洗

作用：
1. 读取 MongoDB timing_source_data 集合中的原始/代理数据；
2. 统一日期、列名、数值类型和排序；
3. 写入到 MongoDB timing_cleaned_data 集合；
4. 只做清洗，不计算择时指标。

数据桥接：读取源数据 / 写入清洗后数据均通过 mongo_store 完成。
任一 section 的源数据缺失（或 MongoDB 不可用）时，打印 [SKIP] 并跳过该
section，不影响后续 section 继续执行。

运行：python 01_数据清洗.py
"""

import re
import numpy as np
import pandas as pd

from app.timing_hexagon.mongo_store import load_source_frame, save_cleaned_frame


# 已成功写入清洗后数据的结果表 (输出文件名, DataFrame)。用于末尾构建审计表。
audit_frames = []


def _load_source(name):
    """加载源数据；缺失或读取异常时打印跳过信息并返回 None（由调用方跳过该 section）。"""
    try:
        df = load_source_frame(name)
    except Exception as e:
        print(f"[SKIP] 读取 {name} 异常: {e}")
        return None
    if df is None:
        print(f"[SKIP] 无源数据可清洗: {name}")
        return None
    return df


def _save_clean(out_name, df):
    """写入清洗后数据到 MongoDB，并登记到 audit_frames 供审计使用。"""
    save_cleaned_frame(out_name, df)
    audit_frames.append((out_name, df))


def finish_table(df, date_col="date"):
    """统一日期、去重、排序。"""
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col])
    df = df.drop_duplicates(subset=[date_col], keep="last")
    df = df.sort_values(date_col).reset_index(drop=True)
    return df


def month_end_from_chinese(text):
    """把 2026年06月份 转为 2026-06-30。"""
    text = str(text)
    match = re.search(r"(\d{4})年(\d{1,2})月", text)
    if match is None:
        return pd.NaT
    year = int(match.group(1))
    month = int(match.group(2))
    return pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)


def conservative_monthly_available_date(date_series, release_day=20):
    """
    月度宏观数据的保守可用日。

    原始文件没有逐期发布日期。为避免把统计期末当成已知日，统一假设数据
    在下一自然月的指定日期可用；一般宏观指标取20日，公布更慢的指标另行
    指定。它不是实际发布日期，只是明确、可审计的保守近似。
    """
    period_end = pd.to_datetime(date_series, errors="coerce")
    next_month_start = period_end + pd.offsets.MonthBegin(1)
    return next_month_start + pd.to_timedelta(release_day - 1, unit="D")


def days_after_period_end(date_series, days):
    """季度或低频数据缺少发布日期时使用的保守可用日。"""
    return pd.to_datetime(date_series, errors="coerce") + pd.to_timedelta(days, unit="D")


def quarter_info(text):
    """解析 2026年第1-2季度 或 2026年第1季度。"""
    text = str(text)
    year_match = re.search(r"(\d{4})年", text)
    quarter_numbers = [int(x) for x in re.findall(r"(\d)季度", text)]

    # “第1-2季度”中，正则只会抓到最后一个季度，因此额外抓区间终点。
    range_match = re.search(r"第\d-(\d)季度", text)
    if range_match is not None:
        quarter_numbers.append(int(range_match.group(1)))

    if year_match is None or len(quarter_numbers) == 0:
        return np.nan, np.nan

    year = int(year_match.group(1))
    quarter = max(quarter_numbers)
    return year, quarter


# ============================================================
# 1. 中证800日行情
# ============================================================
market = _load_source("中证800日行情.csv")
if market is not None:
    market = market[["date", "open", "high", "low", "close", "volume", "amount"]].copy()
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        market[col] = pd.to_numeric(market[col], errors="coerce")
    market = finish_table(market)
    market = market.dropna(subset=["close"])
    market = market[market["close"] > 0].reset_index(drop=True)
    _save_clean("中证800日行情_清洗后.csv", market)


# ============================================================
# 2. SHIBOR 1W
# ============================================================
shibor = _load_source("SHIBOR_1W完整序列.csv")
if shibor is not None:
    shibor_date_col = "报告日" if "报告日" in shibor.columns else ("date" if "date" in shibor.columns else shibor.columns[0])
    shibor_val_col = "利率" if "利率" in shibor.columns else ("shibor_1w" if "shibor_1w" in shibor.columns else ("shibor_1w_pct" if "shibor_1w_pct" in shibor.columns else shibor.columns[1]))
    shibor = shibor[[shibor_date_col, shibor_val_col]].rename(columns={shibor_date_col: "date", shibor_val_col: "shibor_1w_pct"})
    shibor["shibor_1w_pct"] = pd.to_numeric(shibor["shibor_1w_pct"], errors="coerce")
    shibor = finish_table(shibor)
    shibor = shibor.dropna(subset=["shibor_1w_pct"])
    _save_clean("SHIBOR_1W_清洗后.csv", shibor)


# ============================================================
# 3. DR007合成代理序列
# 注意：压缩包中没有央行7天逆回购利率历史序列，不能精确计算研报的
# DR007 / 7天逆回购利率 - 1。本文件只保留压缩包已有的合成DR007水平。
# ============================================================
dr007 = _load_source("DR007合成代理序列.csv")
if dr007 is not None:
    dr007 = dr007[["date", "dr007", "data_source"]].copy()
    dr007["dr007"] = pd.to_numeric(dr007["dr007"], errors="coerce")
    dr007 = finish_table(dr007)
    dr007 = dr007.dropna(subset=["dr007"])
    _save_clean("DR007水平代理_清洗后.csv", dr007)


# ============================================================
# 4. M1、M2
# ============================================================
money = _load_source("货币供应量.csv")
if money is not None:
    money_clean = pd.DataFrame()
    money_clean["date"] = money["月份"].map(month_end_from_chinese)
    money_clean["m1_balance_100m"] = pd.to_numeric(money["货币(M1)-数量(亿元)"], errors="coerce")
    money_clean["m1_yoy_pct"] = pd.to_numeric(money["货币(M1)-同比增长"], errors="coerce")
    money_clean["m2_balance_100m"] = pd.to_numeric(money["货币和准货币(M2)-数量(亿元)"], errors="coerce")
    money_clean["m2_yoy_pct"] = pd.to_numeric(money["货币和准货币(M2)-同比增长"], errors="coerce")
    money_clean = finish_table(money_clean)
    money_clean = money_clean.dropna(subset=["m1_yoy_pct", "m2_yoy_pct"])
    money_clean["available_date"] = conservative_monthly_available_date(money_clean["date"])
    _save_clean("货币供应量_清洗后.csv", money_clean)


# ============================================================
# 5. CPI、PPI
# ============================================================
cpi = _load_source("CPI.csv")
ppi = _load_source("PPI.csv")
if cpi is not None and ppi is not None:
    cpi_clean = pd.DataFrame()
    cpi_date_col = "月份" if "月份" in cpi.columns else ("date" if "date" in cpi.columns else cpi.columns[0])
    cpi_val_col = "全国-同比增长" if "全国-同比增长" in cpi.columns else ("cpi_yoy" if "cpi_yoy" in cpi.columns else ("cpi_yoy_pct" if "cpi_yoy_pct" in cpi.columns else cpi.columns[1]))
    if "月份" in cpi.columns and cpi["月份"].notna().any():
        cpi_clean["date"] = cpi[cpi_date_col].map(month_end_from_chinese)
    else:
        cpi_clean["date"] = pd.to_datetime(cpi[cpi_date_col], errors="coerce")
    cpi_clean["cpi_yoy_pct"] = pd.to_numeric(cpi[cpi_val_col], errors="coerce")
    cpi_clean = finish_table(cpi_clean).dropna(subset=["cpi_yoy_pct"])
    cpi_clean["cpi_available_date"] = conservative_monthly_available_date(cpi_clean["date"])

    ppi_clean = pd.DataFrame()
    ppi_date_col = "月份" if "月份" in ppi.columns else ("date" if "date" in ppi.columns else ppi.columns[0])
    ppi_val_col = "当月同比增长" if "当月同比增长" in ppi.columns else ("ppi_yoy" if "ppi_yoy" in ppi.columns else ("ppi_yoy_pct" if "ppi_yoy_pct" in ppi.columns else ppi.columns[1]))
    if "月份" in ppi.columns and ppi["月份"].notna().any():
        ppi_clean["date"] = ppi[ppi_date_col].map(month_end_from_chinese)
    else:
        ppi_clean["date"] = pd.to_datetime(ppi[ppi_date_col], errors="coerce")
    ppi_clean["ppi_yoy_pct"] = pd.to_numeric(ppi[ppi_val_col], errors="coerce")
    ppi_clean = finish_table(ppi_clean).dropna(subset=["ppi_yoy_pct"])
    ppi_clean["ppi_available_date"] = conservative_monthly_available_date(ppi_clean["date"])

    prices = pd.merge(cpi_clean, ppi_clean, on="date", how="outer").sort_values("date").reset_index(drop=True)
    _save_clean("CPI_PPI_清洗后.csv", prices)


# ============================================================
# 6. 现价累计GDP与名义GDP累计同比
# 原始表“国内生产总值-绝对值”为现价累计值；自行计算同季度累计同比。
# ============================================================
gdp = _load_source("GDP现价累计值.csv")
if gdp is not None:
    gdp_rows = []
    for _, row in gdp.iterrows():
        year, quarter = quarter_info(row["季度"])
        if pd.isna(year) or pd.isna(quarter):
            continue
        quarter_end_month = int(quarter) * 3
        date = pd.Timestamp(year=int(year), month=quarter_end_month, day=1) + pd.offsets.MonthEnd(0)
        gdp_rows.append({
            "date": date,
            "year": int(year),
            "quarter": int(quarter),
            "nominal_gdp_cum_100m": pd.to_numeric(row["国内生产总值-绝对值"], errors="coerce"),
            "real_gdp_yoy_pct_official": pd.to_numeric(row["国内生产总值-同比增长"], errors="coerce"),
        })

    gdp_clean = pd.DataFrame(gdp_rows)
    gdp_clean = finish_table(gdp_clean)
    gdp_clean["nominal_gdp_cum_yoy_pct"] = (
        gdp_clean["nominal_gdp_cum_100m"]
        / gdp_clean.groupby("quarter")["nominal_gdp_cum_100m"].shift(1)
        - 1
    ) * 100

    # 保守可用日期：Q1 4月底、Q2 7月底、Q3 10月底、Q4 次年1月底。
    available_dates = []
    for _, row in gdp_clean.iterrows():
        year = int(row["year"])
        quarter = int(row["quarter"])
        if quarter == 1:
            available_dates.append(pd.Timestamp(year=year, month=4, day=30))
        elif quarter == 2:
            available_dates.append(pd.Timestamp(year=year, month=7, day=31))
        elif quarter == 3:
            available_dates.append(pd.Timestamp(year=year, month=10, day=31))
        else:
            available_dates.append(pd.Timestamp(year=year + 1, month=1, day=31))
    gdp_clean["conservative_available_date"] = available_dates
    _save_clean("名义GDP_清洗后.csv", gdp_clean)


# ============================================================
# 7. 社会融资规模增量
# ============================================================
sf = _load_source("社会融资规模增量.csv")
if sf is not None:
    sf_clean = pd.DataFrame()
    sf_clean["date"] = sf["月份"].map(month_end_from_chinese)
    sf_clean["social_financing_100m"] = pd.to_numeric(sf["当月"], errors="coerce")
    sf_clean = finish_table(sf_clean).dropna(subset=["social_financing_100m"])
    sf_clean["available_date"] = conservative_monthly_available_date(sf_clean["date"])
    _save_clean("社会融资规模增量_清洗后.csv", sf_clean)


# ============================================================
# 8. 制造业PMI
# ============================================================
pmi = _load_source("制造业PMI.csv")
if pmi is not None:
    pmi_clean = pd.DataFrame()
    pmi_date_col = "月份" if "月份" in pmi.columns else ("date" if "date" in pmi.columns else pmi.columns[0])
    pmi_val_col = "制造业-指数" if "制造业-指数" in pmi.columns else ("pmi" if "pmi" in pmi.columns else ("manufacturing_pmi" if "manufacturing_pmi" in pmi.columns else pmi.columns[1]))
    if "月份" in pmi.columns and pmi["月份"].notna().any():
        pmi_clean["date"] = pmi[pmi_date_col].map(month_end_from_chinese)
    else:
        pmi_clean["date"] = pd.to_datetime(pmi[pmi_date_col], errors="coerce")
    pmi_clean["manufacturing_pmi"] = pd.to_numeric(pmi[pmi_val_col], errors="coerce")
    pmi_clean = finish_table(pmi_clean).dropna(subset=["manufacturing_pmi"])
    # PMI通常在统计月末公布；交易执行仍需在指标脚本中推迟到下一交易日。
    pmi_clean["available_date"] = pmi_clean["date"]
    _save_clean("制造业PMI_清洗后.csv", pmi_clean)


# ============================================================
# 9. 全社会用电量同比（仅作为研报“发电量同比”的代理）
# ============================================================
power = _load_source("全社会用电量_发电量代理.csv")
if power is not None:
    power_clean = pd.DataFrame()
    if "统计时间" in power.columns and power["统计时间"].notna().any():
        power_text = power["统计时间"].astype(str).str.strip()
        power_clean["date"] = pd.to_datetime(power_text, format="%Y.%m", errors="coerce") + pd.offsets.MonthEnd(0)
        power_val_col = "全社会用电量同比"
    else:
        date_col = "date" if "date" in power.columns else power.columns[0]
        power_clean["date"] = pd.to_datetime(power[date_col], errors="coerce")
        power_val_col = "power_yoy" if "power_yoy" in power.columns else ("electricity_consumption_yoy_pct" if "electricity_consumption_yoy_pct" in power.columns else power.columns[1])
    power_clean["electricity_consumption_yoy_pct"] = pd.to_numeric(power[power_val_col], errors="coerce")
    power_clean = finish_table(power_clean).dropna(subset=["electricity_consumption_yoy_pct"])
    power_clean["available_date"] = conservative_monthly_available_date(
        power_clean["date"], release_day=25
    )
    _save_clean("全社会用电量同比_代理_清洗后.csv", power_clean)


# ============================================================
# 10. 中证800 PE、PB
# ============================================================
pe = _load_source("中证800PE.csv")
pb = _load_source("中证800PB.csv")
if pe is not None and pb is not None:
    pe_clean = pd.DataFrame()
    pe_date_col = "日期" if "日期" in pe.columns else ("date" if "date" in pe.columns else pe.columns[0])
    pe_clean["date"] = pd.to_datetime(pe[pe_date_col], errors="coerce")
    pe_clean["index_close"] = pd.to_numeric(pe["指数"] if "指数" in pe.columns else pe.get("close", np.nan), errors="coerce")
    pe_clean["pe_ttm_index"] = pd.to_numeric(pe["滚动市盈率"] if "滚动市盈率" in pe.columns else pe.get("pe_weighted", pe.get("pe_ttm", np.nan)), errors="coerce")
    pe_clean["pe_ttm_median"] = pd.to_numeric(pe["滚动市盈率中位数"] if "滚动市盈率中位数" in pe.columns else pe.get("pe_ttm", np.nan), errors="coerce")
    pe_clean = finish_table(pe_clean)

    pb_clean = pd.DataFrame()
    pb_date_col = "日期" if "日期" in pb.columns else ("date" if "date" in pb.columns else pb.columns[0])
    pb_clean["date"] = pd.to_datetime(pb[pb_date_col], errors="coerce")
    pb_clean["pb_index"] = pd.to_numeric(pb["市净率"] if "市净率" in pb.columns else pb.get("pb_weighted", pb.get("pb", np.nan)), errors="coerce")
    pb_clean["pb_median"] = pd.to_numeric(pb["市净率中位数"] if "市净率中位数" in pb.columns else pb.get("pb_median", pb.get("pb", np.nan)), errors="coerce")
    pb_clean = finish_table(pb_clean)

    valuation = pd.merge(pe_clean, pb_clean, on="date", how="outer").sort_values("date").reset_index(drop=True)
    _save_clean("中证800_PE_PB_清洗后.csv", valuation)


# ============================================================
# 11. 中证800股息率（仅最近20个交易日，字段口径待核对）
# ============================================================
dividend = _load_source("中证800股息率_最近20日.csv")
if dividend is not None:
    dividend_clean = pd.DataFrame()
    dividend_clean["date"] = pd.to_datetime(dividend["日期"], errors="coerce")
    dividend_clean["dividend_yield_1_pct"] = pd.to_numeric(dividend["股息率1"], errors="coerce")
    dividend_clean["dividend_yield_2_pct"] = pd.to_numeric(dividend["股息率2"], errors="coerce")
    dividend_clean = finish_table(dividend_clean)
    _save_clean("中证800股息率_最近20日_清洗后.csv", dividend_clean)


# ============================================================
# 12. 10年期国债收益率
# ============================================================
bond = _load_source("中国国债收益率.csv")
if bond is not None:
    bond_clean = pd.DataFrame()
    bond_date_col = "日期" if "日期" in bond.columns else ("date" if "date" in bond.columns else bond.columns[0])
    bond_val_col = "中国国债收益率10年" if "中国国债收益率10年" in bond.columns else ("bond_yield_10y_pct" if "bond_yield_10y_pct" in bond.columns else ("bond_yield_10y" if "bond_yield_10y" in bond.columns else bond.columns[1]))
    bond_clean["date"] = pd.to_datetime(bond[bond_date_col], errors="coerce")
    bond_clean["bond_yield_10y_pct"] = pd.to_numeric(bond[bond_val_col], errors="coerce")
    bond_clean = finish_table(bond_clean).dropna(subset=["bond_yield_10y_pct"])
    _save_clean("10年期国债收益率_清洗后.csv", bond_clean)


# ============================================================
# 13. 新增投资者
# ============================================================
accounts = _load_source("新增投资者.csv")
if accounts is not None:
    accounts_clean = pd.DataFrame()
    if "数据日期" in accounts.columns and accounts["数据日期"].notna().any():
        accounts_clean["date"] = pd.to_datetime(accounts["数据日期"].astype(str), format="%Y-%m", errors="coerce") + pd.offsets.MonthEnd(0)
        acc_val_col = "新增投资者-数量"
    else:
        date_col = "date" if "date" in accounts.columns else accounts.columns[0]
        accounts_clean["date"] = pd.to_datetime(accounts[date_col], errors="coerce")
        acc_val_col = "new_investors_10k" if "new_investors_10k" in accounts.columns else ("new_investors" if "new_investors" in accounts.columns else accounts.columns[1])
    accounts_clean["new_investors_10k"] = pd.to_numeric(accounts[acc_val_col], errors="coerce")
    accounts_clean = finish_table(accounts_clean).dropna(subset=["new_investors_10k"])
    accounts_clean["available_date"] = conservative_monthly_available_date(
        accounts_clean["date"], release_day=30
    )
    _save_clean("新增投资者_清洗后.csv", accounts_clean)


# 北向资金指标已移除（数据源不可用）




# ============================================================
# 15. 沪深融资融券余额与净两融额
# ============================================================
margin_sh = _load_source("上交所两融.csv")
margin_sz = _load_source("深交所两融.csv")
if margin_sh is not None and margin_sz is not None:
    margin_sh_clean = pd.DataFrame()
    margin_sh_clean["date"] = pd.to_datetime(margin_sh["日期"], errors="coerce")
    margin_sh_clean["margin_sh"] = pd.to_numeric(margin_sh["融资融券余额"], errors="coerce")
    margin_sh_fin = pd.to_numeric(margin_sh["融资余额"] if "融资余额" in margin_sh.columns else margin_sh["融资融券余额"], errors="coerce")
    margin_sh_sec = pd.to_numeric(margin_sh["融券余额"] if "融券余额" in margin_sh.columns else 0.0, errors="coerce").fillna(0.0)
    margin_sh_clean["margin_sh_net"] = margin_sh_fin - margin_sh_sec
    margin_sh_clean = finish_table(margin_sh_clean)

    margin_sz_clean = pd.DataFrame()
    margin_sz_clean["date"] = pd.to_datetime(margin_sz["日期"], errors="coerce")
    margin_sz_clean["margin_sz"] = pd.to_numeric(margin_sz["融资融券余额"], errors="coerce")
    margin_sz_fin = pd.to_numeric(margin_sz["融资余额"] if "融资余额" in margin_sz.columns else margin_sz["融资融券余额"], errors="coerce")
    margin_sz_sec = pd.to_numeric(margin_sz["融券余额"] if "融券余额" in margin_sz.columns else 0.0, errors="coerce").fillna(0.0)
    margin_sz_clean["margin_sz_net"] = margin_sz_fin - margin_sz_sec
    margin_sz_clean = finish_table(margin_sz_clean)

    margin = pd.merge(margin_sh_clean, margin_sz_clean, on="date", how="outer").sort_values("date").reset_index(drop=True)
    margin["both_markets_available"] = margin["margin_sh"].notna() & margin["margin_sz"].notna()
    # 两市任一缺失时不把单市场余额误当作全市场合计。
    margin["margin_total"] = margin[["margin_sh", "margin_sz"]].sum(axis=1, min_count=2)
    margin["margin_net"] = margin[["margin_sh_net", "margin_sz_net"]].sum(axis=1, min_count=2)
    _save_clean("融资融券余额_清洗后.csv", margin)


# ============================================================
# 16. 50ETF QVIX
# ============================================================
qvix = _load_source("50ETF_QVIX.csv")
if qvix is not None:
    # 爬虫把 QVIX 级别写入 vix_proxy 列（源为 50ETF QVIX），01 仅做统一日期清洗。
    if "vix_proxy" not in qvix.columns:
        print("[SKIP] 50ETF_QVIX.csv 缺 vix_proxy 列，跳过 50ETF QVIX 清洗。")
    else:
        qvix_clean = qvix[["date", "vix_proxy"]].rename(columns={"vix_proxy": "qvix"})
        qvix_clean["qvix"] = pd.to_numeric(qvix_clean["qvix"], errors="coerce")
        qvix_clean = finish_table(qvix_clean).dropna(subset=["qvix"])
        _save_clean("50ETF_QVIX_清洗后.csv", qvix_clean)


# ============================================================
# 17. 全市场基金资产配置（仅作偏股基金仓位代理）
# ============================================================
fund = _load_source("基金资产配置_代理.csv")
if fund is not None:
    fund_clean = pd.DataFrame()
    fund_clean["date"] = pd.to_datetime(fund["报告期"], errors="coerce")
    fund_clean["all_fund_equity_position_pct"] = pd.to_numeric(fund["股票权益类占净资产比例"], errors="coerce")
    fund_clean["fund_count"] = pd.to_numeric(fund["基金覆盖家数"], errors="coerce")
    fund_clean = finish_table(fund_clean).dropna(subset=["all_fund_equity_position_pct"])
    # 季度基金配置采用期末后45天的保守可用日，避免从季末当天开始回填。
    fund_clean["available_date"] = days_after_period_end(fund_clean["date"], 45)
    _save_clean("全市场基金股票仓位_代理_清洗后.csv", fund_clean)


# ============================================================
# 18. 行业新高新低代理、行业分歧度代理
# ============================================================
breadth = _load_source("行业新高新低_代理.csv")
if breadth is not None:
    breadth_clean = breadth[["date", "sector_count", "nh_ratio", "nl_ratio"]].copy()
    for col in ["sector_count", "nh_ratio", "nl_ratio"]:
        breadth_clean[col] = pd.to_numeric(breadth_clean[col], errors="coerce")
    breadth_clean = finish_table(breadth_clean)
    _save_clean("行业新高新低_代理_清洗后.csv", breadth_clean)

divergence = _load_source("行业分歧度_代理.csv")
if divergence is not None:
    divergence_clean = divergence[["date", "industry_count", "divergence"]].copy()
    for col in ["industry_count", "divergence"]:
        divergence_clean[col] = pd.to_numeric(divergence_clean[col], errors="coerce")
    divergence_clean = finish_table(divergence_clean)
    _save_clean("行业分歧度_代理_清洗后.csv", divergence_clean)


# ============================================================
# 19. 数据清洗审计表
# ============================================================
audit_rows = []
for out_name, df in audit_frames:
    date = pd.to_datetime(df["date"], errors="coerce") if "date" in df.columns else pd.Series(dtype="datetime64[ns]")
    audit_rows.append({
        "file": out_name,
        "rows": len(df),
        "start_date": date.min().strftime("%Y-%m-%d") if len(date.dropna()) else "",
        "end_date": date.max().strftime("%Y-%m-%d") if len(date.dropna()) else "",
        "duplicate_dates": int(date.duplicated().sum()) if len(date) else 0,
        "total_missing_cells": int(df.isna().sum().sum()),
    })

audit = pd.DataFrame(audit_rows)
print("数据清洗完成。")
print("输出：清洗后结果已写入 MongoDB timing_cleaned_data 集合（以清洗后文件名作为 indicator_name）。")
if not audit.empty:
    print(audit.to_string(index=False))
