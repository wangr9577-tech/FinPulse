"""
DR007数据获取脚本
DR007 = 存款类机构间7天质押式回购利率 (Depository-institution 7-day Pledged Repo Rate)
来源：中国外汇交易中心 (CFETS) / 全国银行间同业拆借中心

尝试多种数据源：
1. CFETS chinamoney 公开数据接口
2. AKShare repo_rate_query (FDR007 - 定盘利率)
3. PBOC 公开数据
"""
import akshare as ak
import pandas as pd
import numpy as np
import requests
import json
from datetime import datetime, timedelta
from app.data_fetchers.crawler.utils import RAW, save_processed, log_fetch, TZ_BEIJING
import time


print("=" * 60)
print("DR007 数据获取")
print("=" * 60)

def fetch_dr007_cfets():
    """
    尝试从CFETS/中国货币网获取DR007数据
    DR007从2014年12月15日开始正式发布
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': 'https://www.chinamoney.com.cn/',
    }

    # Try CFETS data API endpoints
    endpoints = [
        # DR007 daily statistics
        'https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/SddsIntrtyNbd',
        # Bond market data
        'https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/BkCurrency',
        # Repo market data
        'https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/fx/ccpr.json',
    ]

    for url in endpoints:
        try:
            print(f"  尝试: {url}")
            r = requests.post(url, json={}, headers=headers, timeout=15)
            if r.status_code == 200 and len(r.text) > 200:
                try:
                    data = r.json()
                    print(f"  [OK] 返回JSON数据")
                    return data
                except:
                    print(f"  [INFO] 返回非JSON数据, 长度={len(r.text)}")
            else:
                print(f"  [{r.status_code}] 响应过短或无数据")
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {str(e)[:100]}")

    return None


def fetch_dr007_akshare():
    """
    使用AKShare repo_rate_query 获取FDR007作为代理
    FDR007 = 7天定盘回购利率 (Fixing Depository-institution Repo rate)
    与DR007高度相关，是DR007的定盘参考利率
    """
    print("\n[方法2] 使用AKShare repo_rate_query (FDR007)...")
    try:
        df = ak.repo_rate_query()
        if df is not None and not df.empty:
            print(f"  FDR007 shape: {df.shape}, cols: {list(df.columns)}")
            print(f"  日期范围: {df['date'].min()} ~ {df['date'].max()}")

            df_out = pd.DataFrame()
            df_out["date"] = pd.to_datetime(df["date"])
            if "FDR007" in df.columns:
                df_out["dr007"] = pd.to_numeric(df["FDR007"], errors="coerce")
            elif "FR007" in df.columns:
                df_out["dr007"] = pd.to_numeric(df["FR007"], errors="coerce")
            df_out = df_out.dropna(subset=["date", "dr007"]).sort_values("date")
            return df_out
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {str(e)[:100]}")
    return None


def fetch_dr007_sina():
    """
    尝试从新浪财经获取Shibor/回购利率数据
    """
    print("\n[方法3] 尝试新浪财经接口...")
    try:
        # Sina finance SHIBOR API
        url = "https://vip.stock.finance.sina.com.cn/q/go.php/vIR_MarketRanking/kind/shibor/index.phtml"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            print(f"  返回长度: {len(r.text)}")
            # Check if it contains repo-related data
            if '回购' in r.text or 'DR' in r.text:
                print(f"  [OK] 页面包含回购/DR数据")
            else:
                print(f"  [INFO] 页面可能不包含DR数据")
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {str(e)[:100]}")
    return None


def fetch_dr007_eastmoney():
    """
    尝试从东方财富获取DR007数据
    使用东方财富数据中心的回购利率接口
    """
    print("\n[方法4] 尝试东方财富接口...")
    try:
        # East Money daily repo data - search for the right report ID
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"

        # Try to find interbank repo rates
        # The data might be in the bond section
        report_names = [
            "RPT_IMP_INTRESTRATEN",  # Same as rate_interbank
        ]

        for rpt in report_names:
            # Try different indicator IDs for repo rates
            for indicator_id in ["DR007", "FDR007", "R007"]:
                params = {
                    "reportName": rpt,
                    "columns": "ALL",
                    "pageNumber": 1,
                    "pageSize": 5,
                    "sortColumns": "REPORT_DATE",
                    "sortTypes": -1,
                    "filter": f'(INDICATOR_ID="{indicator_id}")',
                }
                try:
                    r = requests.get(url, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                    if r.status_code == 200:
                        data = r.json()
                        if data.get('success') and data.get('result', {}).get('data'):
                            print(f"  [OK] {rpt} + {indicator_id}: {len(data['result']['data'])}条")
                            return data
                except:
                    pass
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {str(e)[:100]}")
    return None


def construct_dr007_from_shibor():
    """
    使用SHIBOR 1W作为DR007的长期历史代理
    SHIBOR 1W与DR007的相关系数约0.95
    对于2006-2014年（DR007发布前），SHIBOR 1W是唯一可用的短期利率基准
    """
    print("\n[方法5] 使用SHIBOR 1W构建DR007历史代理...")
    try:
        df = ak.rate_interbank(market="上海银行同业拆借市场", symbol="Shibor人民币", indicator="1周")
        if df is not None and not df.empty:
            cols = list(df.columns)
            df_out = pd.DataFrame()
            df_out["date"] = pd.to_datetime(df[cols[0]])
            df_out["shibor_1w"] = pd.to_numeric(df[cols[1]], errors="coerce")
            df_out = df_out.dropna(subset=["date", "shibor_1w"]).sort_values("date")
            print(f"  SHIBOR 1W: {len(df_out)}条, {df_out['date'].min().date()} ~ {df_out['date'].max().date()}")
            return df_out
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {str(e)[:100]}")
    return None


# ========== 主流程：合并最优数据源 ==========
print("\n[主流程] 构建DR007最优数据序列...")

# Step 1: Try AKShare FDR007 (most recent and accurate)
df_fdr007 = fetch_dr007_akshare()

# Step 2: Get SHIBOR 1W as long-history proxy
df_shibor = construct_dr007_from_shibor()

if df_shibor is not None:
    shibor_out = df_shibor.copy()
    shibor_out["ma60"] = shibor_out["shibor_1w"].rolling(60, min_periods=60).mean()
    shibor_out["historical_q10"] = (
        shibor_out["ma60"].expanding(min_periods=250).quantile(0.10).shift(1)
    )
    shibor_out["signal_score"] = (
        shibor_out["ma60"] < shibor_out["historical_q10"]
    ).astype(int)
    save_processed(shibor_out, "SHIBOR_1W_日度.csv", "liquidity")

    print(f"\n[合并] 构建DR007完整序列...")

    # DR007 was launched on 2014-12-15
    # Before that, use SHIBOR 1W with spread adjustment
    # After that, use FDR007 if available, otherwise SHIBOR 1W

    dr007_start = pd.Timestamp("2014-12-15")

    # Calculate historical spread between SHIBOR 1W and FDR007
    if df_fdr007 is not None and len(df_fdr007) > 0:
        merged = pd.merge(df_shibor, df_fdr007, on="date", how="left", suffixes=("_shibor", "_fdr"))

        # For overlapping period, calculate the spread
        overlap = merged.dropna(subset=["dr007", "shibor_1w"])
        if len(overlap) > 60:
            avg_spread = (overlap["dr007"] - overlap["shibor_1w"]).mean()
            print(f"  DR007-SHIBOR平均利差: {avg_spread:.4f}% (基于{len(overlap)}个重叠交易日)")
        else:
            # Typical spread: DR007 is usually 5-15bp below SHIBOR 1W
            avg_spread = -0.10
            print(f"  [INFO] 重叠数据不足，使用经验利差: {avg_spread}%")

        # Build final series
        df_out = pd.DataFrame()
        df_out["date"] = merged["date"]

        # Where FDR007 is available, use it as DR007 proxy
        df_out["dr007"] = merged["dr007"].fillna(
            merged["shibor_1w"] + avg_spread  # Pre-2023: SHIBOR adjusted by spread
        )

        # Mark data source
        df_out["data_source"] = "FDR007(定盘利率)"
        df_out.loc[merged["dr007"].isna(), "data_source"] = "SHIBOR_1W+利差调整"

    else:
        # No FDR007 data available, use SHIBOR 1W directly
        # Apply typical spread: DR007 ≈ SHIBOR 1W - 10bp
        df_out = pd.DataFrame()
        df_out["date"] = df_shibor["date"]
        df_out["dr007"] = df_shibor["shibor_1w"] - 0.10  # average spread
        df_out["data_source"] = "SHIBOR_1W-10bp(代理)"

    # 原研报偏离度 = DR007 / 7天逆回购政策利率 - 1。当前数据源缺少
    # 政策利率历史，因此明确保留为空，只提供“DR007水平”透明代理。
    df_out["original_deviation_ratio"] = np.nan
    df_out["dr007_level_ma60"] = df_out["dr007"].rolling(60, min_periods=60).mean()
    df_out["level_historical_q10"] = (
        df_out["dr007_level_ma60"].expanding(min_periods=250).quantile(0.10).shift(1)
    )
    df_out["proxy_signal_score"] = (
        df_out["dr007_level_ma60"] < df_out["level_historical_q10"]
    ).astype(int)
    df_out["replication_level"] = "水平代理；不能复现原偏离度"
    df_out["independent_from_shibor"] = df_out["data_source"].eq("FDR007(定盘利率)")

    df_out = df_out.dropna(subset=["dr007"]).sort_values("date")

    save_processed(df_out, "DR007偏离度_日度.csv", "liquidity")
    print(f"\n  [OK] DR007水平代理: {len(df_out)}条, {df_out['date'].min().date()} ~ {df_out['date'].max().date()}")
    print(f"    最新 DR007={df_out['dr007'].iloc[-1]:.4f}%")
    print(f"    数据构成: FDR007覆盖 {(df_out['data_source']=='FDR007(定盘利率)').sum()}条, SHIBOR代理 {(df_out['data_source']!='FDR007(定盘利率)').sum()}条")
    log_fetch("CFETS+SHIBOR", "WARN", f"DR007水平代理 {len(df_out)}条；缺政策利率，原偏离度为空")
else:
    print("\n  [FAIL] 无法获取任何短期利率数据")
    log_fetch("CFETS+SHIBOR", "FAIL", "无法获取短期利率数据")

print("\nDR007数据获取完成!")
