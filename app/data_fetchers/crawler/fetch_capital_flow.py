"""
D组脚本：中国结算 + 沪深交易所 — 资金流向数据
覆盖指标：19 新增开户数 / 21 融资融券余额
数据来源：AKShare + 中国结算 + 上交所/深交所
注：北向资金指标（原指标20）因数据源不可用已移除。
"""
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime
from app.data_fetchers.crawler.utils import (
    RAW, save_processed, log_fetch, TZ_BEIJING,
)


print("=" * 60)
print("D组：资金流向数据")
print("=" * 60)

# ========== 指标19: A股账户新增开户数 ==========
print("\n[指标19/35] A股账户新增开户数...")
try:
    df_account = ak.stock_account_statistics_em()
    if df_account is not None and not df_account.empty:
        print(f"  开户数据形状: {df_account.shape}")
        print(f"  列名: {list(df_account.columns)}")
        print(f"  最近5行:\n{df_account.tail()}")

        save_path = RAW / "chinaclear" / "investor"
        save_path.mkdir(parents=True, exist_ok=True)
        df_account.to_csv(save_path / f"investor_account_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        df_out = pd.DataFrame()
        date_col = next((c for c in df_account.columns if "日期" in c or "date" in c.lower() or "月份" in c), df_account.columns[0])
        account_col = next((c for c in df_account.columns if "新增" in c or "开户" in c or "投资者" in c), df_account.columns[1])

        df_out["date"] = pd.to_datetime(df_account[date_col])
        df_out["date"] = df_out["date"] + pd.offsets.MonthEnd(0)
        df_out["new_investors_10k"] = pd.to_numeric(df_account[account_col], errors="coerce")
        df_out = df_out.dropna(subset=["date", "new_investors_10k"]).sort_values("date")

        df_out["rolling_6m_max"] = df_out["new_investors_10k"].rolling(6, min_periods=3).max()
        df_out["signal"] = "正常"
        df_out.loc[df_out["new_investors_10k"] >= df_out["rolling_6m_max"], "signal"] = "触发反转候选"

        save_processed(df_out, "新增开户数_月度.csv", "flow")
        log_fetch("chinaclear", "OK", f"开户数据 {len(df_out)}条")
        print(f"  [OK] 新增开户: {len(df_out)}条")
    else:
        log_fetch("chinaclear", "WARN", "开户数据为空")
except Exception as e:
    print(f"  [FAIL] 开户数据: {e}")
    log_fetch("chinaclear", "FAIL", str(e))

# ========== 指标21: 融资融券余额 ==========
print("\n[指标21/35] 融资融券余额...")

# 使用 macro_china_market_margin_sh/sz 作为备选方案（macroscopic margin data）
margin_data = {}

# 上交所两融（macro endpoint）
try:
    df_sse_margin = ak.macro_china_market_margin_sh()
    if df_sse_margin is not None and not df_sse_margin.empty:
        print(f"  上交所两融(macro) shape: {df_sse_margin.shape}")
        cols_sh = list(df_sse_margin.columns)
        print(f"  列名: {cols_sh}")

        save_path = RAW / "sse" / "margin"
        save_path.mkdir(parents=True, exist_ok=True)
        df_sse_margin.to_csv(save_path / f"sse_margin_macro_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        # Parse columns: 日期, 融资余额(亿), 融资买入额(亿), 融券余量(亿), 融券余额(亿), 融券卖出量(亿), 融资融券余额(亿)
        margin_data["sh"] = df_sse_margin
        log_fetch("sse_margin", "OK", f"上交所两融(macro) {len(df_sse_margin)}条")

        # 同步上交所两融明细到 source_data（01_数据清洗读上交所两融.csv，避免两融数据停留在旧时间点）
        try:
            sh_source = pd.DataFrame({
                "日期": pd.to_datetime(df_sse_margin["日期"], errors="coerce"),
                "融资融券余额": pd.to_numeric(df_sse_margin["融资融券余额"], errors="coerce"),
                "融资余额": pd.to_numeric(df_sse_margin["融资余额"], errors="coerce"),
                "融券余额": pd.to_numeric(df_sse_margin["融券余额"], errors="coerce"),
                "融资买入额": pd.to_numeric(df_sse_margin["融资买入额"], errors="coerce"),
            })
            sh_source = sh_source.dropna(subset=["日期", "融资融券余额"]).sort_values("日期").reset_index(drop=True)
            save_processed(sh_source, "上交所两融.csv", "flow")
            print(f"  [OK] 上交所两融同步source_data: {len(sh_source)}条")
        except Exception as e_sh_src:
            print(f"  [WARN] 上交所两融同步source_data失败: {e_sh_src}")
except Exception as e:
    print(f"  [WARN] 上交所两融(macro): {type(e).__name__}: {str(e)[:80]}")
    log_fetch("sse_margin", "FAIL", str(e))

# 深交所两融（macro endpoint）
try:
    df_szse_margin = ak.macro_china_market_margin_sz()
    if df_szse_margin is not None and not df_szse_margin.empty:
        print(f"  深交所两融(macro) shape: {df_szse_margin.shape}")
        cols_sz = list(df_szse_margin.columns)
        print(f"  列名: {cols_sz}")

        save_path = RAW / "szse" / "margin"
        save_path.mkdir(parents=True, exist_ok=True)
        df_szse_margin.to_csv(save_path / f"szse_margin_macro_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        margin_data["sz"] = df_szse_margin
        log_fetch("szse_margin", "OK", f"深交所两融(macro) {len(df_szse_margin)}条")

        # 同步深交所两融明细到 source_data
        try:
            sz_source = pd.DataFrame({
                "日期": pd.to_datetime(df_szse_margin["日期"], errors="coerce"),
                "融资融券余额": pd.to_numeric(df_szse_margin["融资融券余额"], errors="coerce"),
                "融资余额": pd.to_numeric(df_szse_margin["融资余额"], errors="coerce"),
                "融券余额": pd.to_numeric(df_szse_margin["融券余额"], errors="coerce"),
                "融资买入额": pd.to_numeric(df_szse_margin["融资买入额"], errors="coerce"),
            })
            sz_source = sz_source.dropna(subset=["日期", "融资融券余额"]).sort_values("日期").reset_index(drop=True)
            save_processed(sz_source, "深交所两融.csv", "flow")
            print(f"  [OK] 深交所两融同步source_data: {len(sz_source)}条")
        except Exception as e_sz_src:
            print(f"  [WARN] 深交所两融同步source_data失败: {e_sz_src}")
except Exception as e:
    print(f"  [WARN] 深交所两融(macro): {type(e).__name__}: {str(e)[:80]}")
    log_fetch("szse_margin", "FAIL", str(e))

# 合成融资融券总量
if margin_data:
    print(f"\n  [合成] 合并沪深两融数据...")
    try:
        # Process SH margin data
        sh_df = margin_data.get("sh")
        if sh_df is not None:
            cols = list(sh_df.columns)
            date_col = cols[0]
            # Find total margin balance column (融资融券余额)
            total_cols = [c for c in cols if "融资融券" in c]
            financing_cols = [c for c in cols if "融资余额" in c]

            sh_out = pd.DataFrame()
            sh_out["date"] = pd.to_datetime(sh_df[date_col])
            if total_cols:
                sh_out["margin_sh"] = pd.to_numeric(sh_df[total_cols[0]], errors="coerce")
            elif len(cols) > 1:
                sh_out["margin_sh"] = pd.to_numeric(sh_df.iloc[:, 1], errors="coerce")
            sh_out = sh_out.dropna(subset=["date", "margin_sh"]).sort_values("date")
            sh_out["date"] = sh_out["date"]

        sz_df = margin_data.get("sz")
        if sz_df is not None:
            cols_sz = list(sz_df.columns)
            date_col_sz = cols_sz[0]
            total_cols_sz = [c for c in cols_sz if "融资融券" in c]

            sz_out = pd.DataFrame()
            sz_out["date"] = pd.to_datetime(sz_df[date_col_sz])
            if total_cols_sz:
                sz_out["margin_sz"] = pd.to_numeric(sz_df[total_cols_sz[0]], errors="coerce")
            elif len(cols_sz) > 1:
                sz_out["margin_sz"] = pd.to_numeric(sz_df.iloc[:, 1], errors="coerce")
            sz_out = sz_out.dropna(subset=["date", "margin_sz"]).sort_values("date")

        # Merge SH and SZ
        if sh_out is not None and sz_out is not None:
            df_margin_total = pd.merge(sh_out, sz_out, on="date", how="outer")
        elif sh_out is not None:
            df_margin_total = sh_out.copy()
            df_margin_total["margin_sz"] = np.nan
        else:
            df_margin_total = sz_out.copy()
            df_margin_total["margin_sh"] = np.nan

        df_margin_total["margin_total"] = df_margin_total.get("margin_sh", 0).fillna(0) + df_margin_total.get("margin_sz", 0).fillna(0)
        df_margin_total = df_margin_total.sort_values("date")

        # Compute signals
        df_margin_total["ma60"] = df_margin_total["margin_total"].rolling(60, min_periods=20).mean()
        df_margin_total["ma120"] = df_margin_total["margin_total"].rolling(120, min_periods=60).mean()
        df_margin_total["trend"] = "震荡"
        df_margin_total.loc[df_margin_total["ma60"] > df_margin_total["ma120"], "trend"] = "上行"
        df_margin_total.loc[df_margin_total["ma60"] < df_margin_total["ma120"], "trend"] = "下行"

        df_margin_total["q10"] = df_margin_total["margin_total"].expanding(min_periods=250).quantile(0.10)
        df_margin_total["q90"] = df_margin_total["margin_total"].expanding(min_periods=250).quantile(0.90)

        save_processed(df_margin_total, "融资融券余额_日度.csv", "flow")
        print(f"  [OK] 融资融券余额: {len(df_margin_total)}条, SH={len(sh_out) if sh_out is not None else 0}, SZ={len(sz_out) if sz_out is not None else 0}")
        log_fetch("margin", "OK", f"两融余额 {len(df_margin_total)}条")
    except Exception as e:
        print(f"  [FAIL] 合成两融失败: {e}")
        log_fetch("margin", "FAIL", str(e))
else:
    log_fetch("margin", "WARN", "无两融数据可用")

print("\nD组数据爬取完成！")
