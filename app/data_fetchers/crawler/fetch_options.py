"""
G组脚本：上交所期权 — CPR、VIX与SKEW
覆盖指标：33 CPR(认购认沽成交比) / 34 QVIX(Quantile VIX) / 35 SKEW(代理)
数据来源：AKShare (option_sse_daily_sina, index_option qvix)
"""
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime
from app.data_fetchers.crawler.utils import (
    RAW, save_processed, log_fetch, TZ_BEIJING,
)


print("=" * 60)
print("G组：期权数据")
print("=" * 60)

# ========== 指标33: CPR (认购认沽成交比率) ==========
# [已删除] AKShare option_sse_daily_sina 仅返回23条数据(2022-01~2022-02)
# 无法区分认购/认沽品种，且数据量不足以支撑统计分析
# 用户确认：放弃该指标
print("\n[指标33/35] 期权认购认沽成交比率(CPR)...")
print("  [SKIP] 用户确认放弃 - 数据仅23条且无法区分认购/认沽")
log_fetch("sse", "SKIP", "CPR: 用户确认放弃, 数据不可用")

# ========== 指标34: QVIX (中国版VIX) ==========
print("\n[指标34/35] QVIX (期权隐含波动率指数)...")
try:
    # 50ETF QVIX - quantile-based VIX from SSE options
    df_qvix_50 = ak.index_option_50etf_qvix()
    if df_qvix_50 is not None and not df_qvix_50.empty:
        print(f"  50ETF QVIX shape: {df_qvix_50.shape}")
        print(f"  列名: {list(df_qvix_50.columns)}")
        print(f"  日期范围: {df_qvix_50['date'].min()} ~ {df_qvix_50['date'].max()}")

        save_path = RAW / "sse" / "options"
        save_path.mkdir(parents=True, exist_ok=True)
        df_qvix_50.to_csv(save_path / f"50etf_qvix_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        # QVIX as VIX proxy
        df_vix = pd.DataFrame()
        df_vix["date"] = pd.to_datetime(df_qvix_50["date"])
        df_vix["vix_proxy"] = pd.to_numeric(df_qvix_50["close"], errors="coerce")
        df_vix = df_vix.dropna(subset=["date", "vix_proxy"]).sort_values("date")

        df_vix["ma5"] = df_vix["vix_proxy"].rolling(5, min_periods=3).mean()
        df_vix["ma20"] = df_vix["vix_proxy"].rolling(20, min_periods=5).mean()
        df_vix["ma60"] = df_vix["vix_proxy"].rolling(60, min_periods=20).mean()
        df_vix["q10"] = df_vix["vix_proxy"].expanding(min_periods=250).quantile(0.10)
        df_vix["q25"] = df_vix["vix_proxy"].expanding(min_periods=250).quantile(0.25)
        df_vix["q50"] = df_vix["vix_proxy"].expanding(min_periods=250).quantile(0.50)
        df_vix["q75"] = df_vix["vix_proxy"].expanding(min_periods=250).quantile(0.75)
        df_vix["q90"] = df_vix["vix_proxy"].expanding(min_periods=250).quantile(0.90)

        df_vix["signal"] = "正常"
        df_vix.loc[df_vix["vix_proxy"] < df_vix["q25"], "signal"] = "低波动(多头)"  # low vol = bullish
        df_vix.loc[df_vix["vix_proxy"] > df_vix["q75"], "signal"] = "高波动(谨慎)"
        df_vix.loc[df_vix["vix_proxy"] > df_vix["q90"], "signal"] = "极高波动(恐慌)"

        save_processed(df_vix, "QVIX_日度.csv", "options")
        print(f"  [OK] QVIX: {len(df_vix)}条, 最新={df_vix['vix_proxy'].iloc[-1]:.2f}")
        log_fetch("sse", "OK", f"QVIX {len(df_vix)}条")

        # 同步 QVIX 原始序列到 source_data（01_数据清洗读 50ETF_QVIX.csv 的 date/close 列）
        try:
            save_processed(
                df_vix[["date", "vix_proxy"]].rename(columns={"vix_proxy": "close"}),
                "50ETF_QVIX.csv",
                "options",
            )
            print(f"  [OK] QVIX同步source_data: {len(df_vix)}条")
        except Exception as e_qvix_src:
            print(f"  [WARN] QVIX同步source_data失败: {e_qvix_src}")
    else:
        log_fetch("sse", "WARN", "QVIX数据为空")
except Exception as e:
    print(f"  [FAIL] QVIX: {type(e).__name__}: {e}")
    log_fetch("sse", "FAIL", str(e))

# 获取300ETF QVIX作为补充
print("\n[补充] 300ETF QVIX...")
try:
    df_qvix_300 = ak.index_option_300etf_qvix()
    if df_qvix_300 is not None and not df_qvix_300.empty:
        print(f"  300ETF QVIX shape: {df_qvix_300.shape}")
        save_path = RAW / "sse" / "options"
        save_path.mkdir(parents=True, exist_ok=True)
        df_qvix_300.to_csv(save_path / f"300etf_qvix_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        df_300 = pd.DataFrame()
        df_300["date"] = pd.to_datetime(df_qvix_300["date"])
        df_300["vix_300_proxy"] = pd.to_numeric(df_qvix_300["close"], errors="coerce")
        df_300 = df_300.dropna().sort_values("date")
        save_processed(df_300, "QVIX_300ETF_日度.csv", "options")
        print(f"  [OK] 300ETF QVIX: {len(df_300)}条, 最新={df_300['vix_300_proxy'].iloc[-1]:.2f}")
        log_fetch("sse", "OK", f"300ETF QVIX {len(df_300)}条")
except Exception as e:
    print(f"  [WARN] 300ETF QVIX: {e}")
    log_fetch("sse", "WARN", str(e))

# ========== 指标35: SKEW (代理 - QVIX skewness) ==========
print("\n[指标35/35] SKEW(代理)...")
try:
    # Use QVIX data to compute skewness proxy
    df_qvix = ak.index_option_50etf_qvix()
    if df_qvix is not None and not df_qvix.empty:
        df_qvix["date"] = pd.to_datetime(df_qvix["date"])
        df_qvix["close"] = pd.to_numeric(df_qvix["close"], errors="coerce")
        df_qvix = df_qvix.dropna(subset=["close"]).sort_values("date")

        # Compute rolling skewness of QVIX as SKEW proxy
        # Higher skewness → tail risk is higher
        returns = df_qvix.set_index("date")["close"].pct_change().dropna()
        skew_20 = returns.rolling(20, min_periods=10).skew()
        skew_60 = returns.rolling(60, min_periods=20).skew()

        df_skew = pd.DataFrame({
            "date": returns.index,
            "qvix_return": returns.values,
            "skew_20d": skew_20.values,
            "skew_60d": skew_60.values,
        })

        df_skew["signal"] = "正常"
        df_skew.loc[df_skew["skew_20d"] > 1.0, "signal"] = "正偏(乐观)"
        df_skew.loc[df_skew["skew_20d"] < -1.0, "signal"] = "负偏(尾部风险)"

        save_processed(df_skew, "SKEW_日度.csv", "options")
        print(f"  [OK] SKEW: {len(df_skew)}条, 最新 skew_20d={df_skew['skew_20d'].iloc[-1]:.2f}")
        log_fetch("sse", "OK", f"SKEW {len(df_skew)}条")
    else:
        log_fetch("sse", "WARN", "SKEW: QVIX数据为空")
except Exception as e:
    print(f"  [WARN] SKEW: {type(e).__name__}: {e}")
    log_fetch("sse", "WARN", str(e))

print("\nG组数据爬取完成!")
