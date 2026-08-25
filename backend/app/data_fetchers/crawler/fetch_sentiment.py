"""
F组脚本：市场情绪数据
覆盖指标：29 成交热度 / 30 行业分歧度 / 31 偏股基金仓位 / 32 NLP情绪(代理)
数据来源：AKShare
"""
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime
from app.data_fetchers.crawler.utils import (
    RAW, save_processed, log_fetch, TZ_BEIJING,
)


print("=" * 60)
print("F组：市场情绪数据")
print("=" * 60)

# ========== 指标29: 成交热度（沪深300 成交金额） ==========
print("\n[指标29/35] 成交热度（沪深300 成交金额）...")
try:
    # 使用 stock_zh_index_daily_em 获取含成交金额(amount)的数据
    # 如果失败则回退到 stock_zh_index_daily (sina源, 只有volume)
    df_hs300 = None
    for attempt in range(3):
        try:
            df_hs300 = ak.stock_zh_index_daily_em(symbol="sh000300")
            if df_hs300 is not None and not df_hs300.empty:
                break
        except Exception as e:
            print(f"  EM尝试{attempt+1}失败: {type(e).__name__}, 等待重试...")
            import time
            time.sleep(3)
    # Fallback to sina source
    if df_hs300 is None:
        print(f"  EM全部失败, 回退到stock_zh_index_daily(sina源)")
        try:
            df_hs300 = ak.stock_zh_index_daily(symbol="sh000300")
        except Exception as e2:
            print(f"  Sina源也失败: {type(e).__name__}")

    if df_hs300 is not None and not df_hs300.empty:
        print(f"  沪深300行情形状: {df_hs300.shape}")
        print(f"  列名: {list(df_hs300.columns)}")

        save_path = RAW / "csindex" / "hs300"
        save_path.mkdir(parents=True, exist_ok=True)
        df_hs300.to_csv(save_path / f"hs300_daily_em_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        df_out = pd.DataFrame()
        df_out["date"] = pd.to_datetime(df_hs300["date"])
        df_out["close"] = pd.to_numeric(df_hs300["close"], errors="coerce")

        # 使用成交金额(amount) 替代成交量(volume)
        if "amount" in df_hs300.columns:
            df_out["turnover_amount"] = pd.to_numeric(df_hs300["amount"], errors="coerce")
            print(f"  使用 成交金额(amount) 列")
        elif "volume" in df_hs300.columns:
            df_out["turnover_amount"] = pd.to_numeric(df_hs300["volume"], errors="coerce")
            print(f"  [WARN] amount列不存在，回退到volume")
        else:
            df_out["turnover_amount"] = np.nan

        df_out = df_out.dropna(subset=["date", "turnover_amount"]).sort_values("date")

        # 过去三个月成交金额 = 60日均值
        df_out["heat_3m"] = df_out["turnover_amount"].rolling(60, min_periods=30).mean()

        # 5年滚动标准化 (1260个交易日 ≈ 5年)
        df_out["rolling_mean"] = df_out["heat_3m"].rolling(1260, min_periods=120).mean()
        df_out["rolling_std"] = df_out["heat_3m"].rolling(1260, min_periods=120).std(ddof=1)
        df_out["cold_line"] = df_out["rolling_mean"] - df_out["rolling_std"]
        df_out["hot_line"] = df_out["rolling_mean"] + df_out["rolling_std"]

        # Z-score
        df_out["zscore"] = (df_out["heat_3m"] - df_out["rolling_mean"]) / df_out["rolling_std"]

        df_out["signal"] = "正常"
        df_out.loc[df_out["heat_3m"] < df_out["cold_line"], "signal"] = "过冷"
        df_out.loc[df_out["heat_3m"] > df_out["hot_line"], "signal"] = "过热"

        save_processed(df_out, "成交热度_日度.csv", "sentiment")
        print(f"  [OK] 成交热度(成交金额): {len(df_out)}条, {df_out['date'].min().date()} ~ {df_out['date'].max().date()}")
        print(f"    最新 heat_3m={df_out['heat_3m'].iloc[-1]:.0f}")
        log_fetch("market", "OK", f"成交热度(金额) {len(df_out)}条")
    else:
        log_fetch("market", "WARN", "沪深300行情为空")
except Exception as e:
    print(f"  [FAIL] 成交热度: {type(e).__name__}: {e}")
    log_fetch("market", "FAIL", str(e))

# ========== 指标30: 行业分歧度 ==========
print("\n[指标30/35] 行业分歧度...")
try:
    sw_industry_map = {
        "农林牧渔": "sz399262",
        "采掘": "sz399293",
        "化工": "sz399270",
        "钢铁": "sz399271",
        "有色金属": "sz399272",
        "电子": "sz399281",
        "家用电器": "sz399279",
        "食品饮料": "sz399280",
        "医药生物": "sz399282",
        "银行": "sz399291",
        "非银金融": "sz399292",
        "房地产": "sz399290",
        "计算机": "sz399283",
        "传媒": "sz399284",
        "通信": "sz399285",
        "汽车": "sz399288",
        "机械设备": "sz399289",
        "建筑装饰": "sz399288",
        "电力设备": "sz399286",
        "国防军工": "sz399273",
    }

    industry_returns = {}
    success_count = 0

    for name, code in sw_industry_map.items():
        try:
            df_sw = ak.stock_zh_index_daily(symbol=code)
            if df_sw is not None and not df_sw.empty:
                df_sw["date"] = pd.to_datetime(df_sw["date"])
                df_sw["close"] = pd.to_numeric(df_sw["close"], errors="coerce")
                ret_series = df_sw.set_index("date")["close"].pct_change()
                if len(ret_series.dropna()) >= 1000:
                    industry_returns[name] = ret_series
                    success_count += 1
        except Exception:
            pass

    print(f"  成功获取 {success_count}/{len(sw_industry_map)} 个行业指数")

    if len(industry_returns) >= 8:
        ret_df = pd.DataFrame(industry_returns)
        ret_df = ret_df.dropna(how="all")

        window = 60
        divergence_series = pd.Series(np.nan, index=ret_df.index)

        for i in range(window, len(ret_df)):
            block = ret_df.iloc[i - window:i]
            valid_block = block.dropna(axis=1)
            if valid_block.shape[1] < 6:
                continue
            corr = valid_block.corr()
            corr_vals = corr.values.copy()
            np.fill_diagonal(corr_vals, np.nan)
            avg_corr = np.nanmean(corr_vals)
            divergence_series.iloc[i] = 1.0 - avg_corr

        df_div = pd.DataFrame({
            "date": ret_df.index,
            "industry_count": pd.Series([ret_df.iloc[i].notna().sum() for i in range(len(ret_df))], index=ret_df.index),
            "divergence": divergence_series.values,
        })
        df_div["ma20"] = df_div["divergence"].rolling(20, min_periods=5).mean()

        div_mean = df_div["divergence"].expanding(min_periods=252).mean()
        div_std = df_div["divergence"].expanding(min_periods=252).std(ddof=1)
        df_div["cold_line"] = div_mean - div_std
        df_div["hot_line"] = div_mean + div_std

        df_div["signal"] = "正常"
        df_div.loc[df_div["divergence"] < df_div["cold_line"], "signal"] = "行业趋同(风险预警)"
        df_div.loc[df_div["divergence"] > df_div["hot_line"], "signal"] = "行业分化(正常)"

        save_processed(df_div, "行业分歧度_日度.csv", "sentiment")
        print(f"  [OK] 行业分歧度: {len(df_div)}条, {success_count}个行业, 最新 divergence={df_div['divergence'].iloc[-1]:.3f}")
        log_fetch("market", "OK", f"行业分歧度 {success_count}行业")
    else:
        print(f"  [WARN] 行业指数不足8个({len(industry_returns)}), 跳过行业分歧度")
        log_fetch("market", "WARN", f"行业分歧度: 仅{len(industry_returns)}行业")
except Exception as e:
    print(f"  [FAIL] 行业分歧度: {type(e).__name__}: {e}")
    log_fetch("market", "FAIL", str(e))

# ========== 指标31: 偏股基金仓位 ==========
print("\n[指标31/35] 偏股基金仓位...")
try:
    # 使用 ak.fund_report_asset_allocation_cninfo 获取全市场基金资产配置汇总数据
    # 该接口返回：报告期, 基金覆盖计数, 股票权益占净资产百分比, 债券固定收益占净资产百分比, ...
    df_position = ak.fund_report_asset_allocation_cninfo()

    if df_position is not None and not df_position.empty:
        cols = list(df_position.columns)
        print(f"  基金仓位数据 shape: {df_position.shape}")
        print(f"  列名: {cols}")
        print(f"  日期范围: {df_position.iloc[:, 0].min()} ~ {df_position.iloc[:, 0].max()}")

        save_path = RAW / "market" / "fund_position"
        save_path.mkdir(parents=True, exist_ok=True)
        df_position.to_csv(save_path / f"fund_position_{datetime.now(TZ_BEIJING).strftime('%Y%m%d')}.csv", index=False, encoding="utf-8-sig")

        # 列名映射 (中文列名)
        date_col = cols[0]       # 报告期
        count_col = cols[1]      # 基金覆盖计数
        equity_col = cols[2]     # 股票权益占净资产百分比

        # 解析季度数据
        df_quarterly = pd.DataFrame()
        df_quarterly["date"] = pd.to_datetime(df_position[date_col])
        df_quarterly["fund_count"] = pd.to_numeric(df_position[count_col], errors="coerce")
        df_quarterly["equity_position"] = pd.to_numeric(df_position[equity_col], errors="coerce")
        df_quarterly = df_quarterly.dropna(subset=["date", "equity_position"]).sort_values("date")

        print(f"  季度数据: {len(df_quarterly)}条")
        print(f"  最新仓位: {df_quarterly['equity_position'].iloc[-1]:.2f}%")

        # 扩展到日频 (前向填充)
        # 确保日期为tz-naive，避免与pandas操作冲突
        df_quarterly["date"] = pd.to_datetime(df_quarterly["date"].astype(str)).dt.tz_localize(None)

        # 首先需要CSI 800交易日历
        trading_dates = None
        for attempt in range(3):
            try:
                df_csi800 = ak.stock_zh_index_daily_em(symbol="sh000906")
                if df_csi800 is not None and not df_csi800.empty:
                    trading_dates = pd.to_datetime(df_csi800["date"].astype(str)).tz_localize(None)
                    trading_dates = trading_dates.sort_values()
                    break
            except Exception:
                import time
                time.sleep(2)
        if trading_dates is None:
            try:
                df_csi800 = ak.stock_zh_index_daily(symbol="sh000906")
                if df_csi800 is not None and not df_csi800.empty:
                    trading_dates = pd.to_datetime(df_csi800["date"].astype(str)).tz_localize(None)
                    trading_dates = trading_dates.sort_values()
            except Exception:
                pass
        if trading_dates is None:
            # Fallback to business days (tz-naive)
            trading_dates = pd.date_range(
                str(df_quarterly["date"].min().date()),
                str(datetime.now(TZ_BEIJING).date()),
                freq="B"
            )

        daily_calendar = pd.DataFrame({"date": pd.to_datetime(trading_dates)})
        daily_calendar = daily_calendar.sort_values("date")

        # 前向填充：每个交易日使用最近季度的仓位数据
        df_daily = pd.merge_asof(
            daily_calendar,
            df_quarterly[["date", "equity_position", "fund_count"]],
            on="date",
            direction="backward"
        )

        initial_len = len(df_daily)
        df_daily = df_daily.dropna(subset=["equity_position"])
        print(f"  日频扩展: {initial_len}个交易日 → {len(df_daily)}条有效数据")

        # 信号计算
        # MA5 平滑
        df_daily["position_ma5"] = df_daily["equity_position"].rolling(5, min_periods=2).mean()

        # 多窗口滚动回归β (使用不同窗口的滚动统计作为仓位变化敏感度)
        for window in [20, 40, 60, 120]:
            col_name = f"position_ma{window}"
            df_daily[col_name] = df_daily["equity_position"].rolling(window, min_periods=max(5, window // 4)).mean()

        # ±1倍标准差通道 (基于全历史 expanding)
        df_daily["position_mean"] = df_daily["equity_position"].expanding(min_periods=10).mean()
        df_daily["position_std"] = df_daily["equity_position"].expanding(min_periods=10).std(ddof=1)

        df_daily["overheat_line"] = df_daily["position_mean"] + df_daily["position_std"]  # +1σ 过热
        df_daily["oversold_line"] = df_daily["position_mean"] - df_daily["position_std"]  # -1σ 过冷

        # 仓位变动率 (用于判断加仓/减仓)
        df_daily["position_change"] = df_daily["position_ma5"].diff(20)  # 20日仓位变化

        # 信号
        df_daily["signal"] = "中性"
        df_daily.loc[df_daily["position_ma5"] > df_daily["overheat_line"], "signal"] = "情绪过热(高仓位)"
        df_daily.loc[df_daily["position_ma5"] < df_daily["oversold_line"], "signal"] = "情绪过冷(低仓位)"

        save_processed(df_daily, "偏股基金仓位_日度.csv", "sentiment")
        print(f"  [OK] 偏股基金仓位: {len(df_daily)}条, 最新仓位MA5={df_daily['position_ma5'].iloc[-1]:.2f}%")
        print(f"    过热线={df_daily['overheat_line'].iloc[-1]:.2f}%, 过冷线={df_daily['oversold_line'].iloc[-1]:.2f}%")
        log_fetch("market", "OK", f"偏股基金仓位 {len(df_daily)}条")
    else:
        print(f"  [WARN] 基金仓位数据为空")
        log_fetch("market", "WARN", "基金仓位: 数据为空")
except Exception as e:
    print(f"  [FAIL] 偏股基金仓位: {type(e).__name__}: {e}")
    log_fetch("market", "FAIL", str(e))

# ========== 指标32: NLP情绪(代理) ==========
print("\n[指标32/35] NLP情绪(代理)...")
print("  [INFO] 股吧文本爬取需要遵守平台规则，生成占位文件")
print("  后续可基于东方财富股吧公开接口进行增量爬取和情感分析")

df_nlp_placeholder = pd.DataFrame({
    "date": pd.date_range("2010-01-01", "2026-07-23", freq="D"),
    "post_count": np.nan,
    "sentiment_score": np.nan,
    "zscore": np.nan,
    "signal": "C级代理_待实现",
})
save_processed(df_nlp_placeholder, "NLP情绪_日度.csv", "sentiment")
log_fetch("forum", "WARN", "NLP情绪: 占位文件")

print("\nF组数据爬取完成!")
