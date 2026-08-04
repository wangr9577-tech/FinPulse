"""
B组脚本：国家统计局 — 宏观经济与通胀数据
覆盖指标：7 制造业PMI / 8 发电量同比 / 9 库存周期 / 10 A股景气度 / 11 CPI同比 / 12 PPI同比
数据来源：AKShare
"""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime
from utils import (
    RAW, save_processed, log_fetch,
    parse_chinese_date, TZ_BEIJING,
)

print("=" * 60)
print("B组: 宏观经济数据爬取")
print("=" * 60)

# ========== 指标7: 制造业 PMI ==========
print("\n[指标7/35] 制造业 PMI...")
try:
    df_pmi = ak.macro_china_pmi()
    if df_pmi is not None and not df_pmi.empty:
        print(f"  PMI shape: {df_pmi.shape}, cols: {list(df_pmi.columns)}")

        save_path = RAW / "nbs" / "pmi"
        save_path.mkdir(parents=True, exist_ok=True)
        df_pmi.to_csv(save_path / f"pmi_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        date_col = [c for c in df_pmi.columns if "月" in c or "date" in c.lower()][0]
        pmi_col = [c for c in df_pmi.columns if "制造" in c and "指数" in c][0]

        df_out = pd.DataFrame()
        df_out["date"] = parse_chinese_date(df_pmi[date_col])
        df_out["date"] = df_out["date"] + pd.offsets.MonthEnd(0)
        df_out["pmi"] = pd.to_numeric(df_pmi[pmi_col], errors="coerce")
        df_out = df_out.dropna(subset=["date", "pmi"]).sort_values("date")

        df_out["ma6"] = df_out["pmi"].rolling(6, min_periods=3).mean()
        df_out["ma12"] = df_out["pmi"].rolling(12, min_periods=6).mean()
        df_out["trend"] = "震荡"
        df_out.loc[df_out["ma6"] > df_out["ma12"], "trend"] = "上行"
        df_out.loc[df_out["ma6"] < df_out["ma12"], "trend"] = "下行"
        df_out["above_50"] = df_out["pmi"] > 50
        df_out["source_url"] = "https://data.stats.gov.cn/"

        save_processed(df_out, "制造业PMI_月度.csv", "macro")
        print(f"  [OK] PMI: {len(df_out)}条, 范围 {df_out['date'].min().date()} ~ {df_out['date'].max().date()}")
        log_fetch("nbs", "OK", f"PMI {len(df_out)}条")
    else:
        log_fetch("nbs", "WARN", "PMI数据为空")
except Exception as e:
    print(f"  [FAIL] PMI: {type(e).__name__}: {e}")
    log_fetch("nbs", "FAIL", str(e))

# ========== 指标11: CPI 同比 ==========
print("\n[指标11/35] CPI 同比...")
try:
    df_cpi = ak.macro_china_cpi()
    if df_cpi is not None and not df_cpi.empty:
        print(f"  CPI shape: {df_cpi.shape}, cols: {list(df_cpi.columns)}")

        save_path = RAW / "nbs" / "cpi"
        save_path.mkdir(parents=True, exist_ok=True)
        df_cpi.to_csv(save_path / f"cpi_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        date_col = [c for c in df_cpi.columns if "月" in c][0]
        cpi_col = "全国-同比增长"
        if cpi_col not in df_cpi.columns:
            cpi_col = [c for c in df_cpi.columns if "同比增长" in c and "全国" in c][0]

        df_out = pd.DataFrame()
        df_out["date"] = parse_chinese_date(df_cpi[date_col])
        df_out["date"] = df_out["date"] + pd.offsets.MonthEnd(0)
        df_out["cpi_yoy"] = pd.to_numeric(df_cpi[cpi_col], errors="coerce")
        df_out = df_out.dropna(subset=["date", "cpi_yoy"]).sort_values("date")

        df_out["q10"] = df_out["cpi_yoy"].expanding(min_periods=36).quantile(0.10)
        df_out["q90"] = df_out["cpi_yoy"].expanding(min_periods=36).quantile(0.90)
        df_out["signal"] = "正常"
        df_out.loc[df_out["cpi_yoy"] < df_out["q10"], "signal"] = "低通胀(多头候选)"
        df_out.loc[df_out["cpi_yoy"] > df_out["q90"], "signal"] = "高通胀(空头候选)"

        save_processed(df_out, "CPI同比_月度.csv", "macro")
        print(f"  [OK] CPI: {len(df_out)}条, 最新 cpi_yoy={df_out['cpi_yoy'].iloc[-1]}")
        log_fetch("nbs", "OK", f"CPI {len(df_out)}条")
except Exception as e:
    print(f"  [FAIL] CPI: {type(e).__name__}: {e}")
    log_fetch("nbs", "FAIL", str(e))

# ========== 指标12: PPI 同比 ==========
print("\n[指标12/35] PPI 同比...")
try:
    df_ppi = ak.macro_china_ppi()
    if df_ppi is not None and not df_ppi.empty:
        print(f"  PPI shape: {df_ppi.shape}, cols: {list(df_ppi.columns)}")

        save_path = RAW / "nbs" / "ppi"
        save_path.mkdir(parents=True, exist_ok=True)
        df_ppi.to_csv(save_path / f"ppi_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        date_col = [c for c in df_ppi.columns if "月" in c][0]
        ppi_col = "当月同比增长"
        if ppi_col not in df_ppi.columns:
            ppi_col = [c for c in df_ppi.columns if "同比增长" in c][0]

        df_out = pd.DataFrame()
        df_out["date"] = parse_chinese_date(df_ppi[date_col])
        df_out["date"] = df_out["date"] + pd.offsets.MonthEnd(0)
        df_out["ppi_yoy"] = pd.to_numeric(df_ppi[ppi_col], errors="coerce")
        df_out = df_out.dropna(subset=["date", "ppi_yoy"]).sort_values("date")

        df_out["q10"] = df_out["ppi_yoy"].expanding(min_periods=36).quantile(0.10)
        df_out["q90"] = df_out["ppi_yoy"].expanding(min_periods=36).quantile(0.90)
        df_out["signal"] = "正常"
        df_out.loc[df_out["ppi_yoy"] < df_out["q10"], "signal"] = "低通胀(多头候选)"
        df_out.loc[df_out["ppi_yoy"] > df_out["q90"], "signal"] = "高通胀(空头候选)"

        save_processed(df_out, "PPI同比_月度.csv", "macro")
        print(f"  [OK] PPI: {len(df_out)}条, 最新 ppi_yoy={df_out['ppi_yoy'].iloc[-1]}")
        log_fetch("nbs", "OK", f"PPI {len(df_out)}条")
except Exception as e:
    print(f"  [FAIL] PPI: {type(e).__name__}: {e}")
    log_fetch("nbs", "FAIL", str(e))

# ========== 指标8: 发电量同比 ==========
print("\n[指标8/35] 发电量同比...")
try:
    df_power = ak.macro_china_society_electricity()
    if df_power is not None and not df_power.empty:
        print(f"  发电量 shape: {df_power.shape}, cols: {list(df_power.columns)}")

        save_path = RAW / "nbs" / "power"
        save_path.mkdir(parents=True, exist_ok=True)
        df_power.to_csv(save_path / f"power_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        # Parse power generation data
        cols_pw = list(df_power.columns)
        date_col_pw = [c for c in cols_pw if "月" in c or "时间" in c][0]
        # Find YoY column
        yoy_col = None
        for c in cols_pw:
            if "同比" in c or "增长" in c:
                yoy_col = c
                break
        if yoy_col is None:
            for c in cols_pw:
                if "发电" in c and "量" in c:
                    yoy_col = c
                    break

        if yoy_col:
            df_out = pd.DataFrame()
            df_out["date"] = parse_chinese_date(df_power[date_col_pw])
            df_out["date"] = df_out["date"] + pd.offsets.MonthEnd(0)
            df_out["power_yoy"] = pd.to_numeric(df_power[yoy_col], errors="coerce")
            df_out = df_out.dropna(subset=["date", "power_yoy"]).sort_values("date")

            df_out["ma6"] = df_out["power_yoy"].rolling(6, min_periods=3).mean()
            df_out["ma12"] = df_out["power_yoy"].rolling(12, min_periods=6).mean()
            df_out["trend"] = "震荡"
            df_out.loc[df_out["ma6"] > df_out["ma12"], "trend"] = "上行"
            df_out.loc[df_out["ma6"] < df_out["ma12"], "trend"] = "下行"

            save_processed(df_out, "发电量同比_月度.csv", "macro")
            print(f"  [OK] 发电量: {len(df_out)}条, 最新 yoy={df_out['power_yoy'].iloc[-1]:.2f}%")
            log_fetch("nbs", "OK", f"发电量 {len(df_out)}条")
        else:
            # Save raw anyway
            print(f"  [WARN] 未找到同比列，保存原始数据到processed")
            log_fetch("nbs", "WARN", "发电量: 未找到同比列")
    else:
        log_fetch("nbs", "WARN", "发电量数据为空")
except Exception as e:
    print(f"  [FAIL] 发电量: {type(e).__name__}: {e}")
    log_fetch("nbs", "FAIL", str(e))

# ========== 指标9: 库存周期 ==========
# [已删除] 该指标需要经济景气指数+库存景气指数的四象限分类法
# AKShare仅提供企业景气指数(macro_china_enterprise_boom_index)，不含库存景气指数
# PMI接口(macro_china_pmi)也缺少产成品库存分项
# 用户确认：放弃该指标
print("\n[指标9/35] 库存周期...")
print("  [SKIP] 用户确认放弃 - AKShare缺少库存景气指数分项数据")
log_fetch("nbs", "SKIP", "库存周期: 用户确认放弃, AKShare缺少库存景气指数")

# ========== 指标10: A股景气度 (使用GDP+PMI+PPI合成) ==========
print("\n[指标10/35] A股景气度(B级代理)...")
try:
    # 代理方法：用PMI + PPI + GDP 的等权合成作为景气度指标
    # 获取最新处理的PMI和PPI数据
    pmi_path = RAW / "nbs" / "pmi"
    cpi_path = RAW / "nbs" / "cpi"
    ppi_path = RAW / "nbs" / "ppi"

    df_pmi3 = ak.macro_china_pmi()
    df_ppi3 = ak.macro_china_ppi()
    df_gdp3 = ak.macro_china_gdp()

    if df_pmi3 is not None and not df_ppi3.empty and df_gdp3 is not None:
        # Build monthly PMI series
        date_col = [c for c in df_pmi3.columns if "月" in c][0]
        pmi_col = [c for c in df_pmi3.columns if "制造" in c and "指数" in c][0]
        df_boom = pd.DataFrame()
        df_boom["date"] = parse_chinese_date(df_pmi3[date_col])
        df_boom["date"] = df_boom["date"] + pd.offsets.MonthEnd(0)
        df_boom["pmi"] = pd.to_numeric(df_pmi3[pmi_col], errors="coerce")

        # Add PPI
        ppi_date = [c for c in df_ppi3.columns if "月" in c][0]
        ppi_col = "当月同比增长"
        if ppi_col not in df_ppi3.columns:
            ppi_col = [c for c in df_ppi3.columns if "同比增长" in c][0]
        df_ppi_t = pd.DataFrame()
        df_ppi_t["date"] = parse_chinese_date(df_ppi3[ppi_date])
        df_ppi_t["date"] = df_ppi_t["date"] + pd.offsets.MonthEnd(0)
        df_ppi_t["ppi"] = pd.to_numeric(df_ppi3[ppi_col], errors="coerce")

        df_boom = pd.merge(df_boom, df_ppi_t, on="date", how="left")

        # Normalize and combine
        df_boom = df_boom.dropna(subset=["pmi"]).sort_values("date")
        df_boom["pmi_z"] = (df_boom["pmi"] - df_boom["pmi"].expanding().mean()) / df_boom["pmi"].expanding().std()
        if "ppi" in df_boom.columns:
            df_boom["ppi_z"] = (df_boom["ppi"] - df_boom["ppi"].expanding().mean()) / df_boom["ppi"].expanding().std()
            df_boom["prosperity_index"] = (df_boom["pmi_z"].fillna(0) + df_boom["ppi_z"].fillna(0)) / 2
        else:
            df_boom["prosperity_index"] = df_boom["pmi_z"]

        df_boom["ma6"] = df_boom["prosperity_index"].rolling(6, min_periods=3).mean()
        df_boom["signal"] = "正常"
        df_boom.loc[df_boom["prosperity_index"] > 0.5, "signal"] = "景气上行"
        df_boom.loc[df_boom["prosperity_index"] < -0.5, "signal"] = "景气下行"

        save_processed(df_boom[["date", "pmi", "ppi", "prosperity_index", "ma6", "signal"]], "A股景气度_月度.csv", "macro")
        print(f"  [OK] A股景气度: {len(df_boom)}条, 最新={df_boom['prosperity_index'].iloc[-1]:.2f}")
        log_fetch("nbs", "OK", f"A股景气度 {len(df_boom)}条")
    else:
        log_fetch("nbs", "WARN", "缺少PMI/PPI/GDP，无法合成A股景气度")
except Exception as e:
    print(f"  [FAIL] A股景气度: {type(e).__name__}: {e}")
    log_fetch("nbs", "FAIL", str(e))

# ========== GDP 数据 (供指标5 M2-GDP使用) ==========
print("\n[GDP] 名义GDP增速...")
try:
    df_gdp = ak.macro_china_gdp()
    if df_gdp is not None and not df_gdp.empty:
        print(f"  GDP shape: {df_gdp.shape}, cols: {list(df_gdp.columns)}")
        print(f"  tail:\n{df_gdp.tail()}")
        save_path = RAW / "nbs" / "gdp"
        save_path.mkdir(parents=True, exist_ok=True)
        df_gdp.to_csv(save_path / f"gdp_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")
        print(f"  [OK] GDP: {len(df_gdp)}条")
        log_fetch("nbs", "OK", f"GDP {len(df_gdp)}条")
except Exception as e:
    print(f"  [FAIL] GDP: {e}")
    log_fetch("nbs", "FAIL", str(e))

print("\nB组数据爬取完成!")
