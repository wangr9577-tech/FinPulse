"""
A组脚本：央行与货币网 — 利率与货币供应数据
覆盖指标：1 DR007偏离度(由fetch_dr007.py生成) / 3 M1同比 / 4 M1-PPI剪刀差 / 5 M2-GDP利差 / 6 信贷脉冲
数据来源：AKShare
"""
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime
from app.data_fetchers.crawler.utils import (
    RAW, PROCESSED, save_processed, log_fetch,
    parse_chinese_date, TZ_BEIJING,
)


print("=" * 60)
print("A组: 货币/信用数据爬取")
print("=" * 60)

# ========== 指标1: DR007偏离度 ==========
# DR007数据已由 fetch_dr007.py 独立脚本生成
# 使用 FDR007(定盘利率) + SHIBOR 1W利差调整 构建完整历史序列
# DR007 (存款类机构7天质押式回购利率) 是央行的核心政策利率锚
# 替代了原有的SHIBOR 1W代理方案
print("\n[指标1/35] DR007偏离度...")
print("  [INFO] 由 fetch_dr007.py 独立脚本生成")
print("  注意: 缺少7天逆回购政策利率历史，只能生成DR007水平代理，不能生成原研报偏离度")
print("  保存位置: processed/liquidity/DR007偏离度_日度.csv")
dr007_path = PROCESSED / "liquidity" / "DR007偏离度_日度.csv"
if not dr007_path.exists() or dr007_path.stat().st_size == 0:
    log_fetch("CFETS", "FAIL", "DR007代理文件缺失；请先运行fetch_dr007.py")
    raise FileNotFoundError(f"请先运行 fetch_dr007.py：{dr007_path}")
log_fetch("CFETS", "OK", "已检测到DR007水平代理文件")

# ========== 指标3: M1同比 & M2同比 ==========
print("\n[指标3/35] M1同比 & M2同比...")
df_m1m2 = None
try:
    df_money = ak.macro_china_money_supply()
    if df_money is not None and not df_money.empty:
        print(f"  货币供应量 shape: {df_money.shape}")
        cols = list(df_money.columns)
        print(f"  列名: {cols}")

        save_path = RAW / "pbc" / "money_supply"
        save_path.mkdir(parents=True, exist_ok=True)
        df_money.to_csv(save_path / f"money_supply_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        date_col = [c for c in cols if "月" in c][0]
        m1_col = [c for c in cols if "M1" in c.upper() and "同比" in c][0]
        m2_col = [c for c in cols if "M2" in c.upper() and "同比" in c][0]

        df_out = pd.DataFrame()
        df_out["date"] = parse_chinese_date(df_money[date_col])
        df_out["date"] = df_out["date"] + pd.offsets.MonthEnd(0)
        df_out["m1_yoy"] = pd.to_numeric(df_money[m1_col], errors="coerce")
        df_out["m2_yoy"] = pd.to_numeric(df_money[m2_col], errors="coerce")
        df_out = df_out.dropna(subset=["date", "m1_yoy"]).sort_values("date")

        df_out["m1_ma6"] = df_out["m1_yoy"].rolling(6, min_periods=3).mean()
        df_out["m1_ma12"] = df_out["m1_yoy"].rolling(12, min_periods=6).mean()
        df_out["trend"] = "震荡"
        df_out.loc[df_out["m1_ma6"] > df_out["m1_ma12"], "trend"] = "上行"
        df_out.loc[df_out["m1_ma6"] < df_out["m1_ma12"], "trend"] = "下行"

        save_processed(df_out, "M1同比_月度.csv", "liquidity")
        df_m1m2 = df_out.copy()
        print(f"  [OK] M1: {len(df_out)}条, 最新 m1_yoy={df_out['m1_yoy'].iloc[-1]}%, m2_yoy={df_out['m2_yoy'].iloc[-1]}%")
        print(f"  日期范围: {df_out['date'].min().date()} ~ {df_out['date'].max().date()}")
        log_fetch("pbc", "OK", f"M1/M2 {len(df_out)}条")
    else:
        log_fetch("pbc", "WARN", "货币供应量数据为空")
except Exception as e:
    print(f"  [FAIL] M1/M2: {type(e).__name__}: {e}")
    log_fetch("pbc", "FAIL", str(e))

# ========== 指标4: M1-PPI剪刀差 ==========
print("\n[指标4/35] M1-PPI剪刀差...")
try:
    # Get PPI data
    df_ppi = ak.macro_china_ppi()
    if df_ppi is not None and not df_ppi.empty and df_m1m2 is not None:
        date_col_ppi = [c for c in df_ppi.columns if "月" in c][0]
        ppi_col = "当月同比增长"
        if ppi_col not in df_ppi.columns:
            ppi_col = [c for c in df_ppi.columns if "同比增长" in c][0]

        df_ppi_out = pd.DataFrame()
        df_ppi_out["date"] = parse_chinese_date(df_ppi[date_col_ppi])
        df_ppi_out["date"] = df_ppi_out["date"] + pd.offsets.MonthEnd(0)
        df_ppi_out["ppi_yoy"] = pd.to_numeric(df_ppi[ppi_col], errors="coerce")
        df_ppi_out = df_ppi_out.dropna(subset=["date", "ppi_yoy"]).sort_values("date")

        # Merge M1 and PPI on date
        df_scissor = pd.merge(df_m1m2[["date", "m1_yoy"]], df_ppi_out[["date", "ppi_yoy"]], on="date", how="inner")
        df_scissor["m1_ppi_spread"] = df_scissor["m1_yoy"] - df_scissor["ppi_yoy"]

        # Rolling stats
        df_scissor["ma6"] = df_scissor["m1_ppi_spread"].rolling(6, min_periods=3).mean()
        df_scissor["ma12"] = df_scissor["m1_ppi_spread"].rolling(12, min_periods=6).mean()
        df_scissor["q10"] = df_scissor["m1_ppi_spread"].expanding(min_periods=36).quantile(0.10)
        df_scissor["q90"] = df_scissor["m1_ppi_spread"].expanding(min_periods=36).quantile(0.90)

        df_scissor["signal"] = "正常"
        df_scissor.loc[df_scissor["m1_ppi_spread"] < df_scissor["q10"], "signal"] = "信用紧缩"
        df_scissor.loc[df_scissor["m1_ppi_spread"] > df_scissor["q90"], "signal"] = "信用扩张"

        save_processed(df_scissor, "M1-PPI剪刀差_月度.csv", "liquidity")
        print(f"  [OK] M1-PPI剪刀差: {len(df_scissor)}条, 最新 spread={df_scissor['m1_ppi_spread'].iloc[-1]:.2f}")
        log_fetch("pbc+nbs", "OK", f"M1-PPI剪刀差 {len(df_scissor)}条")
    else:
        print(f"  [WARN] 缺少M1或PPI数据，跳过M1-PPI剪刀差")
        log_fetch("pbc+nbs", "WARN", "缺少M1或PPI数据")
except Exception as e:
    print(f"  [FAIL] M1-PPI剪刀差: {type(e).__name__}: {e}")
    log_fetch("pbc+nbs", "FAIL", str(e))

# ========== 指标5: M2-GDP利差 ==========
print("\n[指标5/35] M2-GDP利差...")
try:
    df_gdp = ak.macro_china_gdp()
    if df_gdp is not None and not df_gdp.empty and df_m1m2 is not None:
        print(f"  GDP shape: {df_gdp.shape}, cols: {list(df_gdp.columns)}")

        save_path = RAW / "nbs" / "gdp"
        save_path.mkdir(parents=True, exist_ok=True)
        df_gdp.to_csv(save_path / f"gdp_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        # Parse GDP data - typically quarterly with columns like 季度, 国内生产总值
        gdp_cols = list(df_gdp.columns)
        date_col_gdp = [c for c in gdp_cols if "季" in c or "季度" in c or "时间" in c][0]
        # Find GDP YoY growth column
        gdp_yoy_col = None
        for c in gdp_cols:
            if "同比" in c and ("GDP" in c.upper() or "生产总值" in c or "增长" in c):
                gdp_yoy_col = c
                break
        if gdp_yoy_col is None:
            for c in gdp_cols:
                if "同比" in c and "增长" in c:
                    gdp_yoy_col = c
                    break

        if gdp_yoy_col:
            df_gdp_out = pd.DataFrame()
            # GDP date format: "2026年第1季度" or "2026年第1-2季度"
            gdp_date_str = df_gdp[date_col_gdp].astype(str).str.replace(r'[年第季度]', '', regex=True).str.split('-').str[0].str.strip()
            df_gdp_out["date"] = pd.to_datetime(gdp_date_str + '01', format='%Y%m%d', errors='coerce')
            df_gdp_out["date"] = df_gdp_out["date"] + pd.offsets.QuarterEnd(0)
            df_gdp_out["gdp_yoy"] = pd.to_numeric(df_gdp[gdp_yoy_col], errors="coerce")
            df_gdp_out = df_gdp_out.dropna(subset=["date", "gdp_yoy"]).sort_values("date")

            # Expand quarterly GDP to monthly (forward fill)
            date_range = pd.date_range(df_gdp_out["date"].min(), df_gdp_out["date"].max(), freq="ME")
            df_gdp_monthly = pd.DataFrame({"date": date_range})
            df_gdp_monthly = pd.merge_asof(df_gdp_monthly, df_gdp_out, on="date", direction="backward")

            # Merge with M2
            df_spread = pd.merge(df_m1m2[["date", "m2_yoy"]], df_gdp_monthly, on="date", how="inner")
            df_spread["m2_gdp_spread"] = df_spread["m2_yoy"] - df_spread["gdp_yoy"]

            df_spread["ma6"] = df_spread["m2_gdp_spread"].rolling(6, min_periods=3).mean()
            df_spread["q10"] = df_spread["m2_gdp_spread"].expanding(min_periods=24).quantile(0.10)
            df_spread["q90"] = df_spread["m2_gdp_spread"].expanding(min_periods=24).quantile(0.90)

            df_spread["signal"] = "正常"
            df_spread.loc[df_spread["m2_gdp_spread"] < df_spread["q10"], "signal"] = "紧缩"
            df_spread.loc[df_spread["m2_gdp_spread"] > df_spread["q90"], "signal"] = "宽松"

            save_processed(df_spread, "M2-GDP利差_月度.csv", "liquidity")
            print(f"  [OK] M2-GDP利差: {len(df_spread)}条, 最新 spread={df_spread['m2_gdp_spread'].iloc[-1]:.2f}")
            log_fetch("pbc+nbs", "OK", f"M2-GDP利差 {len(df_spread)}条")
        else:
            print(f"  [WARN] 未找到GDP同比列")
            log_fetch("nbs", "WARN", "GDP: 未找到同比列")
    else:
        log_fetch("nbs", "WARN", "GDP数据为空或缺少M2")
except Exception as e:
    print(f"  [FAIL] M2-GDP: {type(e).__name__}: {e}")
    log_fetch("pbc+nbs", "FAIL", str(e))

# ========== 指标6: 信贷脉冲（社融） ==========
print("\n[指标6/35] 信贷脉冲（社融）...")
try:
    df_sf = ak.macro_china_new_financial_credit()
    if df_sf is not None and not df_sf.empty:
        print(f"  社融 shape: {df_sf.shape}")
        print(f"  列名: {list(df_sf.columns)}")

        save_path = RAW / "pbc" / "social_financing"
        save_path.mkdir(parents=True, exist_ok=True)
        df_sf.to_csv(save_path / f"soc_fin_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        # Parse the social financing data
        cols_sf = list(df_sf.columns)
        date_col_sf = [c for c in cols_sf if "月" in c or "时间" in c or "日期" in c][0]

        # Find social financing increment column
        sf_col = None
        for c in cols_sf:
            if "社" in c and ("增量" in c or "规模" in c):
                sf_col = c
                break
        if sf_col is None:
            for c in cols_sf:
                if "社会融资" in c:
                    sf_col = c
                    break
        if sf_col is None:
            sf_col = cols_sf[1]

        df_out = pd.DataFrame()
        df_out["date"] = parse_chinese_date(df_sf[date_col_sf])
        df_out["date"] = df_out["date"] + pd.offsets.MonthEnd(0)
        df_out["social_financing"] = pd.to_numeric(df_sf[sf_col], errors="coerce")
        df_out = df_out.dropna(subset=["date", "social_financing"]).sort_values("date")

        # 信贷脉冲 = 12个月滚动求和同比变化率
        df_out["sf_12m_sum"] = df_out["social_financing"].rolling(12, min_periods=6).sum()
        df_out["credit_impulse"] = df_out["sf_12m_sum"].pct_change(12) * 100

        df_out["ma6"] = df_out["credit_impulse"].rolling(6, min_periods=3).mean()
        df_out["signal"] = "正常"
        df_out.loc[df_out["credit_impulse"] > 0, "signal"] = "信贷扩张"
        df_out.loc[df_out["credit_impulse"] < 0, "signal"] = "信贷收缩"

        save_processed(df_out, "信贷脉冲_月度.csv", "liquidity")
        print(f"  [OK] 信贷脉冲: {len(df_out)}条, {df_out['date'].min().date()} ~ {df_out['date'].max().date()}")
        log_fetch("pbc", "OK", f"信贷脉冲 {len(df_out)}条")
    else:
        log_fetch("pbc", "WARN", "社融数据为空")
except Exception as e:
    print(f"  [FAIL] 信贷脉冲: {type(e).__name__}: {e}")
    log_fetch("pbc", "FAIL", str(e))

# ========== 国债收益率 (供指标16 ERP使用) ==========
print("\n[利率基准] 10年期国债收益率...")
try:
    # bond_zh_us_rate returns China-US bond spread data with long history (1990-)
    # Columns: 日期, 中国国债收益率2年, 5年, 10年, 30年, ...
    df_bond = ak.bond_zh_us_rate()
    if df_bond is not None and not df_bond.empty:
        print(f"  国债 shape: {df_bond.shape}, cols: {list(df_bond.columns)}")
        save_path = RAW / "chinamoney" / "bond_yield"
        save_path.mkdir(parents=True, exist_ok=True)
        df_bond.to_csv(save_path / f"bond_yield_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        # Find 10Y China bond yield column
        bond_cols = list(df_bond.columns)
        date_col_b = bond_cols[0]  # 日期
        y10_col = [c for c in bond_cols if "10" in c and "中国" in c]
        if not y10_col:
            y10_col = [c for c in bond_cols if "10年" in c]
        y10_col = y10_col[0] if y10_col else None

        if y10_col:
            df_bond_out = pd.DataFrame()
            df_bond_out["date"] = pd.to_datetime(df_bond[date_col_b], errors="coerce")
            df_bond_out["bond_yield_10y"] = pd.to_numeric(df_bond[y10_col], errors="coerce")
            df_bond_out = df_bond_out.dropna(subset=["date", "bond_yield_10y"]).sort_values("date")

            if len(df_bond_out) > 0:
                save_processed(df_bond_out, "国债收益率10Y_日度.csv", "liquidity")
                print(f"  [OK] 国债10Y: {len(df_bond_out)}条, {df_bond_out['date'].min().date()} ~ {df_bond_out['date'].max().date()}")
                print(f"    最新={df_bond_out['bond_yield_10y'].iloc[-1]:.2f}%")
                log_fetch("chinabond", "OK", f"国债10Y {len(df_bond_out)}条")
            else:
                print(f"  [WARN] 国债过滤后无数据")
                log_fetch("chinabond", "WARN", "国债: 过滤后无数据")
        else:
            print(f"  [WARN] 未找到10年期列，保存全部: {bond_cols}")
            log_fetch("chinabond", "WARN", "国债: 未找到10年期列")
    else:
        log_fetch("chinabond", "WARN", "国债数据为空")
except Exception as e:
    print(f"  [FAIL] 国债: {type(e).__name__}: {e}")
    log_fetch("chinabond", "FAIL", str(e))

print("\nA组数据爬取完成!")
