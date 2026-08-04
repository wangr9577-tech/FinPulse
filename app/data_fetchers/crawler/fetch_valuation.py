"""
C组脚本：中证指数 + 沪深交易所 — 估值数据
覆盖指标：13 PE_TTM中位数 / 14 股息率 / 15 PB / 16 ERP / 17 DCF估值 / 18 AIAE
数据来源：AKShare (legulegu.com PE/PB, csindex 股息率, bond_china_yield)
"""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime
from utils import (
    RAW, save_processed, log_fetch, parse_chinese_date, TZ_BEIJING,
)

print("=" * 60)
print("C组: 估值数据爬取")
print("=" * 60)

# ========== 中证800成分股数据 ==========
print("\n[基础数据] 中证800成分股...")
try:
    df_cons = ak.index_stock_cons_csindex(symbol="000906")
    if df_cons is not None and not df_cons.empty:
        print(f"  中证800成分股: {df_cons.shape[0]}只")
        print(f"  列名: {list(df_cons.columns)}")
        save_path = RAW / "csindex" / "constituents"
        save_path.mkdir(parents=True, exist_ok=True)
        df_cons.to_csv(save_path / f"csi800_constituents_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")
        log_fetch("csindex", "OK", f"成分股: {df_cons.shape[0]}只")
    else:
        log_fetch("csindex", "WARN", "成分股数据为空")
except Exception as e:
    print(f"  [WARN] 成分股获取失败: {e}")
    log_fetch("csindex", "FAIL", str(e))

# ========== 指标13: PE_TTM中位数 ==========
print("\n[指标13/35] PE_TTM中位数（中证800）...")
try:
    df_pe = ak.stock_index_pe_lg(symbol="中证800")
    if df_pe is not None and not df_pe.empty:
        print(f"  PE中证800 shape: {df_pe.shape}")
        cols = list(df_pe.columns)
        print(f"  列名: {cols}")

        save_path = RAW / "csindex" / "pe"
        save_path.mkdir(parents=True, exist_ok=True)
        df_pe.to_csv(save_path / f"pe_csi800_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        # Columns: [0]日期, [1]指数, [2]加权动态市盈率, [3]动态市盈率, [4]动态市盈率分位数,
        #          [5]加权静态市盈率, [6]静态市盈率(TTM), [7]静态市盈率分位数
        df_out = pd.DataFrame()
        date_col = cols[0]  # 日期
        # Use index position: col[6] = 静态市盈率(TTM), col[3] = 动态市盈率 as fallback
        if len(cols) >= 7:
            pe_col = cols[6]  # 静态市盈率
            pe_pct_col = cols[7] if len(cols) > 7 else None  # 静态市盈率分位数
        else:
            pe_col = cols[3]  # 动态市盈率
            pe_pct_col = cols[4] if len(cols) > 4 else None  # 动态市盈率分位数

        df_out["date"] = pd.to_datetime(df_pe[date_col])
        df_out["pe_ttm"] = pd.to_numeric(df_pe[pe_col], errors="coerce")
        if pe_pct_col:
            df_out["pe_percentile"] = pd.to_numeric(df_pe[pe_pct_col], errors="coerce")

        # Also add weighted PE
        for c in cols:
            if "加权" in c and "静态" in c:
                df_out["pe_weighted"] = pd.to_numeric(df_pe[c], errors="coerce")
                break

        df_out = df_out.dropna(subset=["date", "pe_ttm"]).sort_values("date")

        # Rolling percentiles
        df_out["q10"] = df_out["pe_ttm"].expanding(min_periods=250).quantile(0.10)
        df_out["q25"] = df_out["pe_ttm"].expanding(min_periods=250).quantile(0.25)
        df_out["q50"] = df_out["pe_ttm"].expanding(min_periods=250).quantile(0.50)
        df_out["q75"] = df_out["pe_ttm"].expanding(min_periods=250).quantile(0.75)
        df_out["q90"] = df_out["pe_ttm"].expanding(min_periods=250).quantile(0.90)

        df_out["signal"] = "正常"
        df_out.loc[df_out["pe_ttm"] < df_out["q25"], "signal"] = "低估"
        df_out.loc[df_out["pe_ttm"] < df_out["q10"], "signal"] = "极度低估"
        df_out.loc[df_out["pe_ttm"] > df_out["q75"], "signal"] = "高估"
        df_out.loc[df_out["pe_ttm"] > df_out["q90"], "signal"] = "极度高估"

        save_processed(df_out, "PE_TTM_日度.csv", "valuation")
        print(f"  [OK] PE_TTM: {len(df_out)}条, {df_out['date'].min().date()} ~ {df_out['date'].max().date()}")
        print(f"    最新 PE_TTM={df_out['pe_ttm'].iloc[-1]:.2f}")
        log_fetch("csindex", "OK", f"PE_TTM {len(df_out)}条")
    else:
        log_fetch("csindex", "WARN", "PE数据为空")
except Exception as e:
    print(f"  [FAIL] PE_TTM: {type(e).__name__}: {e}")
    log_fetch("csindex", "FAIL", str(e))

# ========== 指标15: PB ==========
print("\n[指标15/35] PB（中证800）...")
try:
    df_pb = ak.stock_index_pb_lg(symbol="中证800")
    if df_pb is not None and not df_pb.empty:
        print(f"  PB中证800 shape: {df_pb.shape}")
        cols_pb = list(df_pb.columns)
        print(f"  列名: {cols_pb}")

        save_path = RAW / "csindex" / "pb"
        save_path.mkdir(parents=True, exist_ok=True)
        df_pb.to_csv(save_path / f"pb_csi800_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        # Columns: 日期, 指数, 市净率, 等权市净率, 市净率中位数
        df_out = pd.DataFrame()
        date_col_pb = cols_pb[0]
        pb_col = [c for c in cols_pb if "市净率" in c and "等权" not in c and "中位数" not in c][0]
        pb_median_col = [c for c in cols_pb if "中位数" in c][0] if any("中位数" in c for c in cols_pb) else None

        df_out["date"] = pd.to_datetime(df_pb[date_col_pb])
        df_out["pb"] = pd.to_numeric(df_pb[pb_col], errors="coerce")
        if pb_median_col:
            df_out["pb_median"] = pd.to_numeric(df_pb[pb_median_col], errors="coerce")
        df_out = df_out.dropna(subset=["date", "pb"]).sort_values("date")

        df_out["q10"] = df_out["pb"].expanding(min_periods=250).quantile(0.10)
        df_out["q25"] = df_out["pb"].expanding(min_periods=250).quantile(0.25)
        df_out["q50"] = df_out["pb"].expanding(min_periods=250).quantile(0.50)
        df_out["q75"] = df_out["pb"].expanding(min_periods=250).quantile(0.75)
        df_out["q90"] = df_out["pb"].expanding(min_periods=250).quantile(0.90)

        df_out["signal"] = "正常"
        df_out.loc[df_out["pb"] < df_out["q25"], "signal"] = "低估"
        df_out.loc[df_out["pb"] < df_out["q10"], "signal"] = "极度低估"
        df_out.loc[df_out["pb"] > df_out["q75"], "signal"] = "高估"
        df_out.loc[df_out["pb"] > df_out["q90"], "signal"] = "极度高估"

        save_processed(df_out, "PB_日度.csv", "valuation")
        print(f"  [OK] PB: {len(df_out)}条, {df_out['date'].min().date()} ~ {df_out['date'].max().date()}")
        print(f"    最新 PB={df_out['pb'].iloc[-1]:.2f}" + (f", 中位数={df_out['pb_median'].iloc[-1]:.2f}" if pb_median_col else ""))
        log_fetch("csindex", "OK", f"PB {len(df_out)}条")
    else:
        log_fetch("csindex", "WARN", "PB数据为空")
except Exception as e:
    print(f"  [FAIL] PB: {type(e).__name__}: {e}")
    log_fetch("csindex", "FAIL", str(e))

# ========== 指标14: 股息率 ==========
# [已删除] AKShare stock_zh_index_value_csindex 仅返回最近20个交易日数据
# 中证指数官网接口限制，无法获取历史股息率
# 用户确认：放弃该指标
print("\n[指标14/35] 股息率（中证800）...")
print("  [SKIP] 用户确认放弃 - csindex接口仅返回20条数据，无法获取历史股息率")
log_fetch("csindex", "SKIP", "股息率: 用户确认放弃, 数据源限制")

# ========== 指标16: 股权风险溢价 (ERP) ==========
print("\n[指标16/35] 股权风险溢价...")
try:
    # ERP = 1/PE_TTM - 10Y国债收益率
    # Use bond_zh_us_rate for long-history 10Y bond yield (1990-)
    df_bond = ak.bond_zh_us_rate()
    bond_ok = False
    df_bond_erp = None
    if df_bond is not None and not df_bond.empty:
        bond_cols = list(df_bond.columns)
        date_col_b = bond_cols[0]  # 日期
        # Find 10Y China bond yield column
        y10_col = [c for c in bond_cols if "10" in c and "中国" in c]
        if not y10_col:
            y10_col = [c for c in bond_cols if "10年" in c]
        y10_col = y10_col[0] if y10_col else None

        if y10_col:
            df_bond_erp = pd.DataFrame()
            df_bond_erp["date"] = pd.to_datetime(df_bond[date_col_b], errors="coerce")
            df_bond_erp["bond_yield_10y"] = pd.to_numeric(df_bond[y10_col], errors="coerce")
            df_bond_erp = df_bond_erp.dropna(subset=["date", "bond_yield_10y"]).sort_values("date")
            bond_ok = len(df_bond_erp) > 0
            print(f"  国债10Y: {len(df_bond_erp)}条, {df_bond_erp['date'].min().date()} ~ {df_bond_erp['date'].max().date()}")
        else:
            print(f"  [WARN] 未找到10年期列: {bond_cols}")
    else:
        print(f"  [WARN] 国债数据为空")

    # Get PE data for ERP computation
    df_pe2 = ak.stock_index_pe_lg(symbol="中证800")
    if df_pe2 is not None and bond_ok:
        cols2 = list(df_pe2.columns)
        df_erp = pd.DataFrame()
        df_erp["date"] = pd.to_datetime(df_pe2.iloc[:, 0])
        pe_val = pd.to_numeric(df_pe2.iloc[:, 3], errors="coerce")  # 动态市盈率(非加权)
        df_erp["earnings_yield"] = 100.0 / pe_val
        df_erp["pe_ttm"] = pe_val

        df_erp = pd.merge(df_erp, df_bond_erp, on="date", how="inner")
        df_erp["erp"] = df_erp["earnings_yield"] - df_erp["bond_yield_10y"]
        df_erp = df_erp.dropna(subset=["erp"]).sort_values("date")

        df_erp["q10"] = df_erp["erp"].expanding(min_periods=250).quantile(0.10)
        df_erp["q25"] = df_erp["erp"].expanding(min_periods=250).quantile(0.25)
        df_erp["q50"] = df_erp["erp"].expanding(min_periods=250).quantile(0.50)
        df_erp["q75"] = df_erp["erp"].expanding(min_periods=250).quantile(0.75)
        df_erp["q90"] = df_erp["erp"].expanding(min_periods=250).quantile(0.90)

        df_erp["signal"] = "正常"
        df_erp.loc[df_erp["erp"] > df_erp["q75"], "signal"] = "高ERP(股票有吸引力)"
        df_erp.loc[df_erp["erp"] > df_erp["q90"], "signal"] = "极高ERP(强烈看多)"
        df_erp.loc[df_erp["erp"] < df_erp["q25"], "signal"] = "低ERP(股票偏贵)"

        save_processed(df_erp, "ERP_日度.csv", "valuation")
        print(f"  [OK] ERP: {len(df_erp)}条, 最新 ERP={df_erp['erp'].iloc[-1]:.2f}%")
        log_fetch("csindex+chinabond", "OK", f"ERP {len(df_erp)}条")
    else:
        log_fetch("csindex+chinabond", "WARN", "PE或国债数据不可用，无法计算ERP")
except Exception as e:
    print(f"  [FAIL] ERP: {type(e).__name__}: {e}")
    log_fetch("csindex+chinabond", "FAIL", str(e))

# ========== 指标17: DCF估值 (C级 - 占位) ==========
print("\n[指标17/35] DCF估值(C级占位)...")
save_path = RAW / "valuation" / "dcf"
save_path.mkdir(parents=True, exist_ok=True)
placeholder = pd.DataFrame({
    "date": pd.date_range("2008-01-01", "2026-06-30", freq="ME"),
    "dcf_value": np.nan,
    "note": "C级指标 - 需要企业自由现金流预测模型"
})
save_processed(placeholder, "DCF估值_月度.csv", "valuation")
log_fetch("valuation", "WARN", "DCF估值为C级占位符")
print(f"  [WARN] DCF: C级指标，占位符已生成")

# ========== 指标18: AIAE指标 (B级 - 代理) ==========
print("\n[指标18/35] AIAE指标(B级代理)...")
try:
    # AIAE = Aggregate Investor Allocation to Equities
    # 代理：巴菲特比例 = A股总市值 / GDP
    try:
        df_mcap = ak.macro_china_stock_market_cap()
        print(f"  总市值 shape: {df_mcap.shape}, cols: {list(df_mcap.columns)}")
    except Exception as e:
        df_mcap = None
        print(f"  总市值获取失败: {e}")

    df_gdp = ak.macro_china_gdp()
    if df_mcap is not None and df_gdp is not None and not df_gdp.empty:
        mcap_cols = list(df_mcap.columns)
        df_aiae = pd.DataFrame()

        # Parse market cap: col 0=统计月份, col 3=市价总值-上海, col 4=市价总值-深圳
        mcap_date_col = mcap_cols[0]
        mcap_sh_col = [c for c in mcap_cols if "市价总值" in c and "上海" in c] or [mcap_cols[3]]
        mcap_sz_col = [c for c in mcap_cols if "市价总值" in c and "深圳" in c] or [mcap_cols[4]]
        df_aiae["date"] = parse_chinese_date(df_mcap[mcap_date_col])
        df_aiae["date"] = df_aiae["date"] + pd.offsets.MonthEnd(0)
        df_aiae["market_cap"] = pd.to_numeric(df_mcap[mcap_sh_col[0]], errors="coerce") + pd.to_numeric(df_mcap[mcap_sz_col[0]], errors="coerce")

        # Parse GDP (format: "2026年第1季度")
        gdp_cols = list(df_gdp.columns)
        gdp_date_col = gdp_cols[0]
        gdp_val_col = gdp_cols[1]
        df_gdp_p = pd.DataFrame()
        gdp_date_str = df_gdp[gdp_date_col].astype(str).str.replace(r'[年第季度]', '', regex=True).str.split('-').str[0].str.strip()
        df_gdp_p["date"] = pd.to_datetime(gdp_date_str + '01', format='%Y%m%d', errors='coerce')
        df_gdp_p["date"] = df_gdp_p["date"] + pd.offsets.QuarterEnd(0)
        df_gdp_p["gdp"] = pd.to_numeric(df_gdp[gdp_val_col], errors="coerce")

        # Merge
        df_aiae = df_aiae.dropna(subset=["date", "market_cap"]).sort_values("date")
        df_gdp_p = df_gdp_p.dropna(subset=["date", "gdp"]).sort_values("date")
        df_aiae = pd.merge_asof(df_aiae, df_gdp_p, on="date", direction="backward")
        df_aiae["buffett_ratio"] = df_aiae["market_cap"] / df_aiae["gdp"]
        df_aiae = df_aiae.dropna(subset=["buffett_ratio"])

        df_aiae["q10"] = df_aiae["buffett_ratio"].expanding(min_periods=24).quantile(0.10)
        df_aiae["q90"] = df_aiae["buffett_ratio"].expanding(min_periods=24).quantile(0.90)
        df_aiae["signal"] = "正常"
        df_aiae.loc[df_aiae["buffett_ratio"] < df_aiae["q10"], "signal"] = "极度低估"
        df_aiae.loc[df_aiae["buffett_ratio"] > df_aiae["q90"], "signal"] = "泡沫区域"

        if len(df_aiae) > 0:
            save_processed(df_aiae, "AIAE_月度.csv", "valuation")
            print(f"  [OK] AIAE: {len(df_aiae)}条, 最新 Buffett Ratio={df_aiae['buffett_ratio'].iloc[-1]:.2f}")
            log_fetch("nbs", "OK", f"AIAE {len(df_aiae)}条")
        else:
            save_processed(df_aiae, "AIAE_月度.csv", "valuation")
            print(f"  [WARN] AIAE: 数据为空，日期解析可能失败")
            log_fetch("nbs", "WARN", "AIAE: 数据为空")
    else:
        placeholder_aiae = pd.DataFrame({
            "date": pd.date_range("2008-01-01", "2026-06-30", freq="ME"),
            "note": "B级指标 - 需要总市值和GDP数据"
        })
        save_processed(placeholder_aiae, "AIAE_月度.csv", "valuation")
        log_fetch("nbs", "WARN", "AIAE: 缺少数据")
except Exception as e:
    print(f"  [WARN] AIAE: {type(e).__name__}: {e}")
    placeholder_aiae = pd.DataFrame({
        "date": pd.date_range("2008-01-01", "2026-06-30", freq="ME"),
        "note": "B级指标 - AIAE代理数据"
    })
    save_processed(placeholder_aiae, "AIAE_月度.csv", "valuation")
    log_fetch("valuation", "WARN", str(e))

# ========== 补充：获取CSI 300和上证50估值数据 ==========
print("\n[补充] 沪深300/上证50 PE/PB...")
for sym in ["沪深300", "上证50"]:
    try:
        df_pe300 = ak.stock_index_pe_lg(symbol=sym)
        if df_pe300 is not None and not df_pe300.empty:
            save_path = RAW / "csindex" / "pe"
            save_path.mkdir(parents=True, exist_ok=True)
            safe_name = sym.replace("/", "_")
            df_pe300.to_csv(save_path / f"pe_{safe_name}_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")
            print(f"  [OK] {sym} PE: {len(df_pe300)}条")
            log_fetch("csindex", "OK", f"PE {sym} {len(df_pe300)}条")
    except Exception as e:
        print(f"  [WARN] {sym} PE: {e}")

print("\nC组数据爬取完成!")
