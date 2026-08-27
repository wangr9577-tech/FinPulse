"""
E组脚本：中证800与全A行情 — 技术指标和市场广度
覆盖指标：22 均线排列 / 23 均线距离 / 24 布林带 / 25 RSI / 26 新高占比 / 27 新低占比 / 28 量价时钟
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
print("E组：技术指标与市场广度")
print("=" * 60)

# ========== 统一获取中证800 (000906) 日行情 ==========
print("\n[基础数据] 中证800指数日行情 (sh000906)...")
INDEX_CODE = "000906"
df_index = None

try:
    # 尝试EM源, 失败则回退sina源
    df_index = None
    for attempt in range(3):
        try:
            df_index = ak.stock_zh_index_daily_em(symbol=f"sh{INDEX_CODE}")
            if df_index is not None and not df_index.empty:
                break
        except Exception as e:
            print(f"  EM尝试{attempt+1}失败: {type(e).__name__}, 等待重试...")
            import time
            time.sleep(3)
    if df_index is None:
        print(f"  EM全部失败, 回退到stock_zh_index_daily(sina源)")
        try:
            df_index = ak.stock_zh_index_daily(symbol=f"sh{INDEX_CODE}")
        except Exception as e2:
            print(f"  Sina源也失败: {type(e).__name__}")

    if df_index is not None and not df_index.empty:
        print(f"  中证800行情形状: {df_index.shape}")
        print(f"  列名: {list(df_index.columns)}")
        print(f"  日期范围: {df_index['date'].min()} ~ {df_index['date'].max()}")

        # 补齐成交金额 (amount)
        if "amount" not in df_index.columns or df_index["amount"].dropna().empty:
            try:
                print("  尝试从中证指数官网 stock_zh_index_hist_csindex 补齐成交额...")
                csindex_hist = ak.stock_zh_index_hist_csindex(symbol="000906")
                if csindex_hist is not None and not csindex_hist.empty:
                    csindex_hist["date"] = pd.to_datetime(csindex_hist["日期"] if "日期" in csindex_hist.columns else csindex_hist["date"])
                    amt_col = "成交金额" if "成交金额" in csindex_hist.columns else ("amount" if "amount" in csindex_hist.columns else None)
                    if amt_col:
                        csindex_hist["amount"] = pd.to_numeric(csindex_hist[amt_col], errors="coerce")
                        df_index["date"] = pd.to_datetime(df_index["date"])
                        df_index = pd.merge(df_index, csindex_hist[["date", "amount"]], on="date", how="left", suffixes=("", "_cs"))
                        if "amount_cs" in df_index.columns:
                            df_index["amount"] = df_index["amount"].fillna(df_index["amount_cs"])
                            df_index.drop(columns=["amount_cs"], inplace=True)
            except Exception as e_cs:
                print(f"  中证官网成交额获取提示: {e_cs}")

            # 原「从本地 source_data/中证800日行情.csv 补齐成交额」已移除：
            # 本地 CSV 层已废弃（Mongo 为唯一存储），且 DATA_DIR 在本模块未定义会触发 NameError。

        # 将中证800日行情写入 MongoDB ('timing_source_data'，indicator_name=中证800日行情.csv)，
        # 供 01_数据清洗 直接读取，替代 raw/csindex 下的 CSV 落盘。
        from app.timing_hexagon.mongo_store import save_source_frame
        try:
            save_source_frame("中证800日行情.csv", df_index)
        except Exception as e_cm:
            print(f"  [WARN] 中证800日行情 Mongo 写入提示: {e_cm}")

        # Standardize
        df_index["date"] = pd.to_datetime(df_index["date"])
        df_index["close"] = pd.to_numeric(df_index["close"], errors="coerce")
        df_index = df_index.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        log_fetch("csindex", "OK", f"中证800行情: {len(df_index)}条")
    else:
        log_fetch("csindex", "WARN", "中证800行情为空")
except Exception as e:
    print(f"  [FAIL] 中证800行情获取失败: {type(e).__name__}: {e}")
    log_fetch("csindex", "FAIL", str(e))

if df_index is not None and not df_index.empty:
    close = df_index["close"]
    dates = df_index["date"]
    # Volume and amount if available
    if "volume" in df_index.columns:
        volume = pd.to_numeric(df_index["volume"], errors="coerce")
    else:
        volume = None
    if "amount" in df_index.columns:
        amount = pd.to_numeric(df_index["amount"], errors="coerce")
    else:
        amount = None

    # ========== 指标22: 均线排列 ==========
    print("\n[指标22/35] 均线排列...")
    try:
        ma10 = close.rolling(10, min_periods=5).mean()
        ma30 = close.rolling(30, min_periods=15).mean()
        ma60 = close.rolling(60, min_periods=30).mean()
        ma90 = close.rolling(90, min_periods=45).mean()

        bull_alignment = (ma10 > ma30) & (ma30 > ma60)
        bull_confirmed = bull_alignment & bull_alignment.shift(1).fillna(False)

        bear_alignment = (ma10 < ma30) & (ma30 < ma60)
        bear_confirmed = bear_alignment & bear_alignment.shift(1).fillna(False)

        df_ma = pd.DataFrame({
            "date": dates,
            "close": close,
            "ma10": ma10,
            "ma30": ma30,
            "ma60": ma60,
            "ma90": ma90,
            "bull_alignment": bull_confirmed,
            "bear_alignment": bear_confirmed,
            "signal": "震荡",
        })
        df_ma.loc[bull_confirmed, "signal"] = "多头排列"
        df_ma.loc[bear_confirmed, "signal"] = "空头排列"

        save_processed(df_ma, "均线排列_日度.csv", "technical")
        print(f"  [OK] 均线排列: {len(df_ma)}条, 多头比例={bull_confirmed.mean():.1%}")
        log_fetch("technical", "OK", f"均线排列 {len(df_ma)}条")
    except Exception as e:
        print(f"  [FAIL] 均线排列计算失败: {e}")

    # ========== 指标23: 均线距离 ==========
    print("\n[指标23/35] 均线距离...")
    try:
        ma_short = close.rolling(10, min_periods=5).mean()
        ma_long = close.rolling(60, min_periods=30).mean()
        distance = (ma_short / ma_long - 1) * 100

        df_dist = pd.DataFrame({
            "date": dates,
            "close": close,
            "ma10": ma_short,
            "ma60": ma_long,
            "distance_pct": distance,
        })

        df_dist["distance_ma252"] = distance.rolling(252, min_periods=60).mean()
        df_dist["distance_std252"] = distance.rolling(252, min_periods=60).std(ddof=1)
        df_dist["distance_zscore"] = (distance - df_dist["distance_ma252"]) / df_dist["distance_std252"]

        df_dist["regime"] = "震荡"
        df_dist.loc[distance > 5, "regime"] = "强烈上行"
        df_dist.loc[distance > 2, "regime"] = "温和上行"
        df_dist.loc[distance < -5, "regime"] = "强烈下行"
        df_dist.loc[distance < -2, "regime"] = "温和下行"

        save_processed(df_dist, "均线距离_日度.csv", "technical")
        print(f"  [OK] 均线距离: {len(df_dist)}条, 最新距离={distance.iloc[-1]:.2f}%")
        log_fetch("technical", "OK", f"均线距离 {len(df_dist)}条")
    except Exception as e:
        print(f"  [FAIL] 均线距离计算失败: {e}")

    # ========== 指标24: 布林带 ==========
    print("\n[指标24/35] 布林带...")
    try:
        mid = close.rolling(20, min_periods=10).mean()
        std20 = close.rolling(20, min_periods=10).std(ddof=1)
        upper = mid + 2 * std20
        lower = mid - 2 * std20
        bb_width = (upper - lower) / mid * 100

        df_bb = pd.DataFrame({
            "date": dates,
            "close": close,
            "mid": mid,
            "upper": upper,
            "lower": lower,
            "bb_width_pct": bb_width,
            "position": "通道内",
        })
        df_bb.loc[close > upper, "position"] = "突破上轨"
        df_bb.loc[close < lower, "position"] = "跌破下轨"

        save_processed(df_bb, "布林带_日度.csv", "technical")
        print(f"  [OK] 布林带: {len(df_bb)}条")
        log_fetch("technical", "OK", f"布林带 {len(df_bb)}条")
    except Exception as e:
        print(f"  [FAIL] 布林带计算失败: {e}")

    # ========== 指标25: RSI ==========
    print("\n[指标25/35] RSI 相对强弱指标...")
    try:
        delta = close.diff()

        def wilder_rsi(series: pd.Series, period: int = 14) -> pd.Series:
            up = series.clip(lower=0)
            down = (-series).clip(lower=0)
            avg_up = up.ewm(alpha=1/period, adjust=False).mean()
            avg_down = down.ewm(alpha=1/period, adjust=False).mean()
            rs = avg_up / avg_down.replace(0, np.nan)
            return 100 - (100 / (1 + rs))

        rsi6 = wilder_rsi(delta, 6)
        rsi14 = wilder_rsi(delta, 14)
        rsi24 = wilder_rsi(delta, 24)

        df_rsi = pd.DataFrame({
            "date": dates,
            "close": close,
            "rsi6": rsi6,
            "rsi14": rsi14,
            "rsi24": rsi24,
            "signal": "中性",
        })
        df_rsi.loc[rsi6 < 20, "signal"] = "超卖(多头候选)"
        df_rsi.loc[rsi6 > 80, "signal"] = "超买(空头候选)"
        df_rsi.loc[(rsi6 > 20) & (rsi6 <= 35), "signal"] = "偏弱"
        df_rsi.loc[(rsi6 >= 65) & (rsi6 < 80), "signal"] = "偏强"

        save_processed(df_rsi, "RSI_日度.csv", "technical")
        print(f"  [OK] RSI: {len(df_rsi)}条, 最新 RSI6={rsi6.iloc[-1]:.1f}, RSI14={rsi14.iloc[-1]:.1f}")
        log_fetch("technical", "OK", f"RSI {len(df_rsi)}条")
    except Exception as e:
        print(f"  [FAIL] RSI计算失败: {e}")

    # ========== 指标26+27: 新高/新低占比 (真实市场广度 - 方案B) ==========
    print("\n[指标26-27/35] 新高/新低占比(行业指数市场广度)...")
    print("  [方案B] 使用SW行业指数250日新高/新低统计作为市场广度代理")
    print("  [说明] AKShare stock_zh_a_hist(个股历史行情)接口网络受限")
    print("         使用~20个SW行业指数替代个股计算市场广度")
    try:
        # SW行业指数列表 (申万行业指数)
        sw_sectors = {
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
            "电力设备": "sz399286",
            "国防军工": "sz399273",
            "公用事业": "sz399295",
            "交通运输": "sz399294",
        }

        sector_high_low = {}  # sector → DataFrame with NH/NL flags
        success_sectors = 0

        for name, code in sw_sectors.items():
            try:
                df_sector = ak.stock_zh_index_daily(symbol=code)
                if df_sector is not None and len(df_sector) > 250:
                    df_sector["date"] = pd.to_datetime(df_sector["date"])
                    df_sector["close"] = pd.to_numeric(df_sector["close"], errors="coerce")
                    df_sector = df_sector.dropna(subset=["close"]).sort_values("date")

                    # 250日最高价/最低价
                    high_250 = df_sector["close"].rolling(250, min_periods=250).max()
                    low_250 = df_sector["close"].rolling(250, min_periods=250).min()

                    # 当日是否创新高/新低 (需要shift避免前视偏差)
                    at_high = df_sector["close"] >= high_250.shift(1)
                    at_low = df_sector["close"] <= low_250.shift(1)

                    sector_high_low[name] = pd.DataFrame({
                        "date": df_sector["date"],
                        "new_high": at_high.astype(int),
                        "new_low": at_low.astype(int),
                    })
                    success_sectors += 1
            except Exception:
                pass

        print(f"  成功获取 {success_sectors}/{len(sw_sectors)} 个行业指数数据")

        if success_sectors >= 8:
            # 合并所有行业的NH/NL数据
            all_highs = None
            all_lows = None

            for name, df_hl in sector_high_low.items():
                if all_highs is None:
                    all_highs = df_hl.set_index("date")["new_high"]
                    all_lows = df_hl.set_index("date")["new_low"]
                else:
                    all_highs = all_highs.add(df_hl.set_index("date")["new_high"], fill_value=0)
                    all_lows = all_lows.add(df_hl.set_index("date")["new_low"], fill_value=0)

            # 新高/新低占比
            nh_ratio = all_highs / success_sectors  # 创新高行业占比
            nl_ratio = all_lows / success_sectors    # 创新低行业占比
            nh_nl_diff = nh_ratio - nl_ratio         # 净新高比例

            df_hl = pd.DataFrame({
                "date": nh_ratio.index,
                "sector_count": success_sectors,
                "nh_sectors": all_highs.values,
                "nl_sectors": all_lows.values,
                "nh_ratio": nh_ratio.values,
                "nl_ratio": nl_ratio.values,
                "nh_nl_diff": nh_nl_diff.values,
            })

            # 20日滚动平滑
            df_hl["nh_ratio_20d"] = df_hl["nh_ratio"].rolling(20, min_periods=5).mean()
            df_hl["nl_ratio_20d"] = df_hl["nl_ratio"].rolling(20, min_periods=5).mean()
            df_hl["nh_nl_diff_20d"] = df_hl["nh_nl_diff"].rolling(20, min_periods=5).mean()

            # 信号
            df_hl["signal"] = "中性"
            df_hl.loc[df_hl["nh_nl_diff"] > 0.2, "signal"] = "强势(多行业创新高)"
            df_hl.loc[df_hl["nh_nl_diff"] < -0.2, "signal"] = "弱势(多行业创新低)"

            df_hl["data_method"] = f"方案B: {success_sectors}个SW行业指数市场广度"

            save_processed(df_hl, "新高新低_日度.csv", "technical")
            print(f"  [OK] 新高新低(行业广度): {len(df_hl)}条, {success_sectors}个行业")
            print(f"    最新 NH_ratio={df_hl['nh_ratio'].iloc[-1]:.2%}, NL_ratio={df_hl['nl_ratio'].iloc[-1]:.2%}")
            print(f"    日期范围: {df_hl['date'].min().date()} ~ {df_hl['date'].max().date()}")
            log_fetch("technical", "OK", f"新高新低(行业广度:{success_sectors}行业) {len(df_hl)}条")
        else:
            print(f"  [WARN] 行业数据不足({success_sectors}个), 回退到指数代理")
            # 回退：使用指数级别新高新低作为最简代理
            high_250 = close.rolling(250, min_periods=250).max()
            low_250 = close.rolling(250, min_periods=250).min()

            df_hl = pd.DataFrame({
                "date": dates,
                "close": close,
                "new_250d_high": (close >= high_250.shift(1)).astype(int),
                "new_250d_low": (close <= low_250.shift(1)).astype(int),
            })

            df_hl["nh_ratio_20d"] = df_hl["new_250d_high"].rolling(20).mean()
            df_hl["nl_ratio_20d"] = df_hl["new_250d_low"].rolling(20).mean()
            df_hl["nh_nl_diff"] = df_hl["nh_ratio_20d"] - df_hl["nl_ratio_20d"]

            df_hl["signal"] = "中性"
            df_hl.loc[df_hl["nh_nl_diff"] > 0.1, "signal"] = "强势(多)"
            df_hl.loc[df_hl["nh_nl_diff"] < -0.1, "signal"] = "弱势(空)"

            df_hl["data_method"] = "方案B回退: 中证800指数250日新高新低代理"

            save_processed(df_hl, "新高新低_日度.csv", "technical")
            print(f"  [OK] 新高新低(指数代理): {len(df_hl)}条 (行业数据不足,回退)")
            log_fetch("technical", "WARN", f"新高新低: 行业数据不足, 回退指数代理 {len(df_hl)}条")
    except Exception as e:
        print(f"  [FAIL] 新高新低计算失败: {e}")
        log_fetch("technical", "FAIL", str(e))

    # ========== 指标28: 量价时钟 ==========
    print("\n[指标28/35] 量价时钟...")
    try:
        ret = close.pct_change()
        vol20 = ret.rolling(20, min_periods=10).std() * np.sqrt(252)

        if amount is not None:
            amt_ma20 = amount.rolling(20, min_periods=10).mean()
            amt_ratio = amount / amt_ma20
        elif volume is not None:
            vol_ma20 = volume.rolling(20, min_periods=10).mean()
            amt_ratio = volume / vol_ma20
        else:
            amt_ratio = pd.Series(np.nan, index=close.index)

        vol_ma20_vol = vol20.rolling(20, min_periods=10).mean()
        vol_trend = vol20 > vol_ma20_vol

        amt_trend_up = amt_ratio > 1.0

        quadrant = pd.Series("未知", index=close.index)
        quadrant[amt_trend_up & vol_trend] = "放量+高波(高风险)"
        quadrant[amt_trend_up & ~vol_trend] = "放量+低波(趋势)"
        quadrant[~amt_trend_up & vol_trend] = "缩量+高波(警惕)"
        quadrant[~amt_trend_up & ~vol_trend] = "缩量+低波(冷淡)"

        df_clock = pd.DataFrame({
            "date": dates,
            "close": close,
            "volatility_20d_ann": vol20,
            "amt_ratio": amt_ratio,
            "quadrant": quadrant,
        })

        save_processed(df_clock, "量价时钟_日度.csv", "technical")
        print(f"  [OK] 量价时钟: {len(df_clock)}条, 象限分布:\n{quadrant.value_counts().to_string()}")
        log_fetch("technical", "OK", f"量价时钟 {len(df_clock)}条")
    except Exception as e:
        print(f"  [FAIL] 量价时钟计算失败: {e}")

else:
    print("\n[!] 中证800行情不可用，跳过所有技术指标计算")

# ========== 补充：获取沪深300行情 ==========
print("\n[补充] 沪深300/上证指数行情...")
for sym, name in [("sh000300", "沪深300"), ("sh000001", "上证综指")]:
    try:
        df_aux = ak.stock_zh_index_daily_em(symbol=sym)
        if df_aux is not None and not df_aux.empty:
            print(f"  [OK] {name}: {len(df_aux)}条, {df_aux['date'].min()} ~ {df_aux['date'].max()}")
            log_fetch("csindex", "OK", f"{name} {len(df_aux)}条")
    except Exception as e:
        print(f"  [WARN] {name}: {e}")

print("\nE组数据爬取完成!")
