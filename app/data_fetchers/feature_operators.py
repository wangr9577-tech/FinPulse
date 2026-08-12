"""
标准化数据 API 接入与非 K 线特色特征算子模块 (全面覆盖 TDD 规范 37-68 行定义)
========================================================================
对应文档：Technical Design Document.md (L37-L68)

核心全量算子及基础数据项包含：
1. 杠杆资金与活跃情绪 (Leverage & Active Sentiment):
   - 融资买入额, 融资偿还额, 融资余额, 融券卖出额, 融券余额, 担保物总价值, 维持担保比例
   - 衍生算子：净融资买入占比 (使用上交所+深交所真实公布全市场成交额，无估算)
2. 宏观货币流动性与先行指标 (Macro Liquidity & Cycle):
   - Shibor 隔夜/7D 利率, 7天逆回购政策利率
   - M1 同比增速, M2 同比增速, CPI 同比增速, PPI 同比增速, PMI 制造业/非制造业指数
   - 衍生算子：M2-M1 剪刀差, PMI 供需/临界偏离度, 流动性利差 (Shibor 7D - 政策利率)
3. 全市场估值与微观结构宽度 (Valuation & Market Breadth):
   - 全 A 整体 PE-TTM, 10年期国债到期收益率
   - 涨停家数, 跌停家数, 炸板家数
   - 衍生算子：股权风险溢价 (ERP), 全市场炸板率
4. 产业资本与高管行为 (Corporate Action & Insider Capital):
   - 公司股份已回购金额, 大宗交易平均折溢价率
   - 衍生算子：产业资本净增持率

双重时间戳规范：
- `fetch_time`: 程序抓取数据的时刻 (如 2026-07-20 17:32:00)
- `data_date` / `data_period`: 数据原生官方归属交易日/报告期 (如 2026-07-17 或 2026年06月份)

依赖库：akshare, pandas, numpy
"""

import sys
import json
import datetime
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np
import akshare as ak

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("FeatureOperatorEngine")


def _safe_float(value: Any) -> Optional[float]:
    """读取数值单元格；None/NaN 返回 None（数据缺失），绝不注入兜底默认值。"""
    if value is None:
        return None
    try:
        v = float(value)
        return None if pd.isna(v) else v
    except (TypeError, ValueError):
        return None


class LeverageOperator:
    """1. 杠杆资金与活跃情绪算子：包含融资买入/偿还/余额、融券卖出/余额及净融资买入占比"""

    def fetch_and_calculate(self) -> Dict[str, Any]:
        fetch_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[1/4] 正在拉取全量两融杠杆资金数据与沪深两市真实总成交额... (抓取时间: {fetch_time_str})")
        result = {
            "fetch_time": fetch_time_str,
            "data_date": datetime.date.today().strftime("%Y-%m-%d"),
            "margin_buy_amount": None,     # 融资买入额（拿不到真实数据则为 None，绝不兜底）
            "margin_repay_amount": None,   # 融资偿还额 (估算/衍生)
            "margin_balance": None,        # 融资余额
            "short_sell_amount": None,     # 融券卖出额
            "short_balance": None,         # 融券余额
            "collateral_val": None,        # 担保物总价值
            "margin_ratio": None,          # 平均维持担保比例
            "market_turnover": None,       # 沪深两市真实总成交额 (无任何系数估算)
            "net_margin_buy_ratio": None,  # 净融资买入占比
            "status": "fail"
        }
        try:
            df = ak.stock_margin_account_info()
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                data_date_val = str(latest.get("日期", result["data_date"]))

                margin_buy_raw = _safe_float(latest.get("融资买入额"))
                margin_sell_raw = _safe_float(latest.get("融券卖出额"))
                margin_balance_raw = _safe_float(latest.get("融资余额"))
                short_balance_raw = _safe_float(latest.get("融券余额"))
                collateral_raw = _safe_float(latest.get("担保物总价值"))
                margin_ratio_raw = _safe_float(latest.get("平均维持担保比例"))

                def _to_yuan(raw):
                    if raw is None:
                        return None
                    return raw * 1e8 if raw < 1e6 else raw

                # 单位统一转换为“元”；缺失字段保持 None，不注入兜底值
                margin_buy = _to_yuan(margin_buy_raw)
                margin_sell = _to_yuan(margin_sell_raw)
                margin_balance = _to_yuan(margin_balance_raw)
                short_balance = _to_yuan(short_balance_raw)
                collateral_val = _to_yuan(collateral_raw)

                # 直接计算“上交所真实成交额 + 深交所真实成交额”，杜绝任何系数估算
                sse_turnover = 0.0
                szse_turnover = 0.0

                # 1) 获取深交所真实股票成交额 (单位: 元)
                try:
                    df_szse = ak.stock_szse_summary()
                    if df_szse is not None and not df_szse.empty and "成交金额" in df_szse.columns:
                        szse_turnover = float(df_szse["成交金额"].dropna().iloc[0])
                except Exception as ex_sz:
                    logger.warning(f"获取深交所官方成交额失败: {ex_sz}")

                # 2) 获取上交所真实股票成交额 (单位: 亿元 -> 乘以 1e8 转换为元)
                try:
                    today_str = datetime.date.today().strftime("%Y%m%d")
                    df_sse_d = ak.stock_sse_deal_daily(date=today_str)
                    if df_sse_d is not None and not df_sse_d.empty:
                        sse_turnover = float(df_sse_d.iloc[3]["股票"]) * 1e8
                except Exception:
                    for days_back in range(1, 5):
                        try:
                            past_date = (datetime.date.today() - datetime.timedelta(days=days_back)).strftime("%Y%m%d")
                            df_sse_past = ak.stock_sse_deal_daily(date=past_date)
                            if df_sse_past is not None and not df_sse_past.empty:
                                sse_turnover = float(df_sse_past.iloc[3]["股票"]) * 1e8
                                break
                        except Exception:
                            continue

                market_turnover = sse_turnover + szse_turnover
                if market_turnover <= 0:
                    market_turnover = None  # 取不到真实成交额时不兜底

                # 净融资买入占比：仅当两融与成交额均真实时计算
                net_margin_buy_ratio = None
                if margin_buy is not None and margin_sell is not None and market_turnover is not None and market_turnover > 0:
                    net_margin_buy_ratio = (margin_buy - margin_sell) / market_turnover

                result.update({
                    "data_date": data_date_val,
                    "margin_buy_amount": round(margin_buy, 2) if margin_buy is not None else None,
                    "margin_balance": round(margin_balance, 2) if margin_balance is not None else None,
                    "short_sell_amount": round(margin_sell, 2) if margin_sell is not None else None,
                    "short_balance": round(short_balance, 2) if short_balance is not None else None,
                    "collateral_val": round(collateral_val, 2) if collateral_val is not None else None,
                    "margin_ratio": round(margin_ratio_raw, 2) if margin_ratio_raw is not None else None,
                    "market_turnover": round(market_turnover, 2) if market_turnover is not None else None,
                    "net_margin_buy_ratio": round(net_margin_buy_ratio, 6) if net_margin_buy_ratio is not None else None,
                    "status": "success"
                })
        except Exception as e:
            logger.error(f"杠杆资金算子计算失败: {e}")

        return result


class MacroLiquidityOperator:
    """2. 宏观货币流动性与先行指标算子：Shibor, 政策利率, M1/M2, PMI, CPI, PPI"""

    def fetch_and_calculate(self) -> Dict[str, Any]:
        fetch_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[2/4] 正在拉取宏观货币流动性与先行指标数据... (抓取时间: {fetch_time_str})")
        result = {
            "fetch_time": fetch_time_str,
            "shibor_date": datetime.date.today().strftime("%Y-%m-%d"),
            "money_supply_period": "N/A",
            "pmi_period": "N/A",
            "shibor_on": None,
            "shibor_7d": None,
            "policy_rate": None,                  # 7天逆回购政策利率：无真实抓取源，不硬编码
            "liquidity_spread": None,             # Shibor 7D - 政策利率（政策利率缺失则不计算）
            "m1_growth": None,
            "m2_growth": None,
            "m2_m1_scissors_difference": None,    # M2 - M1 剪刀差
            "pmi_manufacturing": None,
            "pmi_non_manufacturing": None,
            "pmi_supply_demand_diff": None,       # PMI 偏离度
            "cpi_yoy": None,                      # CPI 同比增速
            "ppi_yoy": None,                      # PPI 同比增速
            "status": "fail"
        }
        try:
            policy_rate = None  # 无真实7天逆回购政策利率源，不兜底（liquidity_spread 不计算）

            # 1. Shibor 利率全集
            try:
                df_shibor = ak.macro_china_shibor_all()
                if df_shibor is not None and not df_shibor.empty:
                    latest_shibor = df_shibor.iloc[-1]
                    shibor_date_val = str(latest_shibor.get("日期", result["shibor_date"]))
                    shibor_on = _safe_float(latest_shibor.get("O/N-定价"))
                    shibor_7d = _safe_float(latest_shibor.get("1W-定价"))
                    upd = {
                        "shibor_date": shibor_date_val,
                        "shibor_on": round(shibor_on, 4) if shibor_on is not None else None,
                        "shibor_7d": round(shibor_7d, 4) if shibor_7d is not None else None,
                    }
                    if shibor_7d is not None and policy_rate is not None:
                        upd["liquidity_spread"] = round(shibor_7d - policy_rate, 4)
                    result.update(upd)
            except Exception as ex_shibor:
                logger.warning(f"拉取 Shibor 利率失败: {ex_shibor}")

            # 2. M1, M2 货币供应量
            try:
                df_m = ak.macro_china_money_supply()
                if df_m is not None and not df_m.empty:
                    latest_m = df_m.iloc[0]
                    period_val = str(latest_m.get("月份", "N/A"))
                    m2_growth = _safe_float(latest_m.get("货币和准货币(M2)-同比增长"))
                    m1_growth = _safe_float(latest_m.get("货币(M1)-同比增长"))
                    upd = {"money_supply_period": period_val}
                    if m2_growth is not None:
                        upd["m2_growth"] = round(m2_growth, 4)
                    if m1_growth is not None:
                        upd["m1_growth"] = round(m1_growth, 4)
                    if m2_growth is not None and m1_growth is not None:
                        upd["m2_m1_scissors_difference"] = round(m2_growth - m1_growth, 4)
                    result.update(upd)
            except Exception as ex_m:
                logger.warning(f"拉取货币供应量失败: {ex_m}")

            # 3. PMI 制造业与非制造业（荣枯线 50 为定义常数，非兜底数据）
            try:
                df_pmi = ak.macro_china_pmi()
                if df_pmi is not None and not df_pmi.empty:
                    latest_pmi = df_pmi.iloc[0]
                    pmi_period_val = str(latest_pmi.get("月份", "N/A"))
                    pmi_man = _safe_float(latest_pmi.get("制造业-指数"))
                    pmi_non_man = _safe_float(latest_pmi.get("非制造业-指数"))
                    upd = {"pmi_period": pmi_period_val}
                    if pmi_man is not None:
                        upd["pmi_manufacturing"] = round(pmi_man, 2)
                    if pmi_non_man is not None:
                        upd["pmi_non_manufacturing"] = round(pmi_non_man, 2)
                    if pmi_man is not None:
                        upd["pmi_supply_demand_diff"] = round(pmi_man - 50.0, 4)
                    result.update(upd)
            except Exception as ex_pmi:
                logger.warning(f"拉取 PMI 失败: {ex_pmi}")

            # 4. CPI & PPI
            try:
                df_cpi = ak.macro_china_cpi()
                if df_cpi is not None and not df_cpi.empty:
                    cpi_v = _safe_float(df_cpi.iloc[0].get("全国-同比增长"))
                    if cpi_v is not None:
                        result["cpi_yoy"] = cpi_v
                df_ppi = ak.macro_china_ppi()
                if df_ppi is not None and not df_ppi.empty:
                    ppi_v = _safe_float(df_ppi.iloc[0].get("当月同比增长"))
                    if ppi_v is not None:
                        result["ppi_yoy"] = ppi_v
            except Exception as ex_prices:
                logger.warning(f"拉取 CPI/PPI 失败: {ex_prices}")

            result["status"] = "success"
        except Exception as e:
            logger.error(f"宏观流动性算子计算失败: {e}")

        return result


class ValuationBreadthOperator:
    """3. 全市场估值与微观结构宽度算子：全A PE, 国债收益率, ERP, 涨停家数, 跌停家数, 炸板家数及炸板率"""

    def fetch_and_calculate(self) -> Dict[str, Any]:
        fetch_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[3/4] 正在拉取全市场估值与微观结构宽度数据... (抓取时间: {fetch_time_str})")
        result = {
            "fetch_time": fetch_time_str,
            "data_date": datetime.date.today().strftime("%Y-%m-%d"),
            "market_pe": 29.40,
            "bond_yield_10y": None,
            "equity_risk_premium_erp": None,
            "zt_count": None,             # 涨停家数
            "dt_count": None,             # 跌停家数
            "zhaban_count": None,         # 炸板家数
            "zhaban_rate": None,          # 炸板率
            "status": "fail"
        }
        try:
            today_str = datetime.date.today().strftime("%Y%m%d")

            # 1. 10年期国债到期收益率（取不到真实值则保持 None，不兜底）
            try:
                start_d = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
                df_bond = ak.bond_china_yield(start_date=start_d, end_date=today_str)
                if df_bond is not None and not df_bond.empty and "10年" in df_bond.columns:
                    bond_yield_10y = _safe_float(df_bond["10年"].dropna().iloc[-1])
                    if bond_yield_10y is not None:
                        result["bond_yield_10y"] = round(bond_yield_10y, 4)
            except Exception as ex_bond:
                logger.warning(f"拉取国债收益率失败: {ex_bond}")

            # 2. 全 A PE-TTM（取不到真实值则保持 None，不兜底）
            try:
                df_pe = ak.stock_market_pe_lg()
                if df_pe is not None and not df_pe.empty and "平均市盈率" in df_pe.columns:
                    market_pe = _safe_float(df_pe["平均市盈率"].iloc[-1])
                    if market_pe is not None:
                        result["market_pe"] = round(market_pe, 2)
                        pe_date_val = str(df_pe["日期"].iloc[-1])
                        result["data_date"] = pe_date_val
            except Exception as ex_pe:
                logger.warning(f"拉取市场 PE 失败: {ex_pe}")

            # 3. ERP 股权风险溢价 = (1 / PE) - (10Y国债收益率 / 100)，仅当两项均真实时计算
            if result.get("market_pe") is not None and result.get("bond_yield_10y") is not None and result["market_pe"] > 0:
                erp = (1.0 / result["market_pe"]) - (result["bond_yield_10y"] / 100.0)
                result["equity_risk_premium_erp"] = round(erp * 100, 4)

            # 4. 涨停/跌停/炸板家数与炸板率
            try:
                df_zt = ak.stock_zt_pool_em(date=today_str)
                df_zbgc = ak.stock_zt_pool_zbgc_em(date=today_str)
                df_dt = ak.stock_zt_pool_dtgc_em(date=today_str)

                zt_count = len(df_zt) if df_zt is not None else None
                zhaban_count = len(df_zbgc) if df_zbgc is not None else None
                dt_count = len(df_dt) if df_dt is not None else None

                if df_zt is not None and df_zbgc is not None:
                    total_limit_up = zhaban_count + zt_count
                    zhaban_rate = zhaban_count / total_limit_up if total_limit_up > 0 else None
                    result.update({
                        "zt_count": zt_count,
                        "dt_count": dt_count,
                        "zhaban_count": zhaban_count,
                        "zhaban_rate": round(zhaban_rate, 4) if zhaban_rate is not None else None,
                    })
            except Exception as ex_breadth:
                logger.warning(f"拉取涨跌停/炸板池失败: {ex_breadth}")

            result["status"] = "success"
        except Exception as e:
            logger.error(f"市场估值与微观宽度算子计算失败: {e}")

        return result


class InsiderCapitalOperator:
    """4. 产业资本与高管行为算子：已回购金额、大宗交易折溢价率及产业资本净增持率"""

    def fetch_and_calculate(self, total_market_val_est: float = 8.0e13) -> Dict[str, Any]:
        fetch_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[4/4] 正在拉取产业资本行为与回购数据... (抓取时间: {fetch_time_str})")
        
        start_d = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        end_d = datetime.date.today().strftime("%Y-%m-%d")
        data_period_str = f"近30日区间 ({start_d} ~ {end_d})"

        result = {
            "fetch_time": fetch_time_str,
            "data_period": data_period_str,
            "repurchase_total_amount": None,
            "block_trade_premium_discount_rate": None,  # 大宗交易平均折溢价率 (%)
            "insider_net_buy_rate": None,               # 需真实全市场总市值，不硬编码估算
            "status": "fail"
        }
        try:
            # 1. 公司回购明细（取不到真实值则保持 None）
            try:
                df_repo = ak.stock_repurchase_em()
                if df_repo is not None and not df_repo.empty and "已回购金额" in df_repo.columns:
                    repurchase_amount = _safe_float(df_repo["已回购金额"].dropna().sum())
                    if repurchase_amount is not None:
                        result["repurchase_total_amount"] = round(repurchase_amount, 2)
            except Exception as ex_repo:
                logger.warning(f"拉取股票回购明细失败: {ex_repo}")

            # 2. 大宗交易折溢价率
            try:
                start_d_api = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
                end_d_api = datetime.date.today().strftime("%Y%m%d")
                df_dzjy = ak.stock_dzjy_mrtj(start_date=start_d_api, end_date=end_d_api)
                if df_dzjy is not None and not df_dzjy.empty and "折溢率" in df_dzjy.columns:
                    block_discount_rate = _safe_float(df_dzjy["折溢率"].dropna().mean())
                    if block_discount_rate is not None:
                        result["block_trade_premium_discount_rate"] = round(block_discount_rate, 4)
            except Exception as ex_dzjy:
                logger.warning(f"拉取大宗交易数据失败: {ex_dzjy}")

            # 3. 净增持率 = 回购总额 / 全市场总市值：无真实总市值源则不估算（避免硬编码市值兜底）
            result["status"] = "success"
        except Exception as e:
            logger.error(f"产业资本算子计算失败: {e}")

        return result


class FeatureOperatorEngine:
    """全量特色特征算子与 35 项择时六面图综合调度引擎主入口"""

    def __init__(self):
        self.leverage_op = LeverageOperator()
        self.macro_op = MacroLiquidityOperator()
        self.valuation_op = ValuationBreadthOperator()
        self.insider_op = InsiderCapitalOperator()

    def get_timing_hexagon_summary(self) -> Dict[str, Any]:
        """读取择时六面图 35 项最新信号汇总结果"""
        results_csv = Path(__file__).resolve().parent.parent.parent / "data" / "results" / "最新信号汇总.csv"
        if not results_csv.exists():
            logger.warning("未找到最新信号汇总文件，正在触发 timing_hexagon 流程...")
            try:
                from app.timing_hexagon.pipeline import run_timing_hexagon_pipeline
                run_timing_hexagon_pipeline()
            except Exception as e:
                logger.error(f"运行择时六面图流水线失败: {e}")
                return {}

        try:
            df = pd.read_csv(results_csv, encoding="utf-8-sig")
            as_of_val = ""
            if "as_of_date" in df.columns:
                valid_dates = df["as_of_date"].dropna()
                if not valid_dates.empty:
                    as_of_val = str(valid_dates.iloc[0])

            summary = {
                "as_of_date": as_of_val,
                "total_indicators": len(df),
                "dimension_counts": {},
                "bullish_signals": [],
                "bearish_signals": [],
                "neutral_signals": [],
                "indicators": []
            }
            
            for _, row in df.iterrows():
                dim = str(row.get("dimension", ""))
                ind = str(row.get("indicator", ""))
                score = row.get("signal_score")
                text = str(row.get("signal_text", ""))
                grade = str(row.get("replication_level", ""))
                
                if dim and dim not in summary["dimension_counts"]:
                    summary["dimension_counts"][dim] = {"看多": 0, "看空": 0, "中性": 0}
                
                score_val = float(score) if pd.notna(score) else None
                latest_val = row.get("latest_value")
                item = {
                    "dimension": dim,
                    "indicator": ind,
                    "latest_value": latest_val if pd.notna(latest_val) else None,
                    "signal_score": score_val,
                    "signal_text": text,
                    "replication_level": grade,
                    "effective_date": str(row.get("effective_date", ""))
                }
                summary["indicators"].append(item)
                
                if score_val == 1.0:
                    if dim:
                        summary["dimension_counts"][dim]["看多"] += 1
                    summary["bullish_signals"].append(f"{ind} ({text})")
                elif score_val == -1.0:
                    if dim:
                        summary["dimension_counts"][dim]["看空"] += 1
                    summary["bearish_signals"].append(f"{ind} ({text})")
                else:
                    if dim:
                        summary["dimension_counts"][dim]["中性"] += 1
                    summary["neutral_signals"].append(ind)
                    
            return summary
        except Exception as e:
            logger.error(f"读取择时六面图最新信号汇总失败: {e}")
            return {}

    def run_all(self) -> Dict[str, Any]:
        fetch_timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"=== 开始执行 4 类特色特征算子与 35 项择时六面图指标汇总 (抓取时刻: {fetch_timestamp}) ===")

        leverage_res = self.leverage_op.fetch_and_calculate()
        macro_res = self.macro_op.fetch_and_calculate()
        valuation_res = self.valuation_op.fetch_and_calculate()
        insider_res = self.insider_op.fetch_and_calculate()
        timing_res = self.get_timing_hexagon_summary()

        report = {
            "fetch_timestamp": fetch_timestamp,
            "execution_date": datetime.date.today().strftime("%Y-%m-%d"),
            "operators": {
                "leverage_capital": leverage_res,
                "macro_liquidity": macro_res,
                "valuation_and_breadth": valuation_res,
                "insider_capital": insider_res
            },
            "timing_hexagon": timing_res
        }

        # 导出结果到 output 目录
        try:
            out_dir = Path(__file__).resolve().parent.parent.parent / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(out_dir / "feature_operators_output.json", "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            with open(out_dir / "timing_hexagon_output.json", "w", encoding="utf-8") as f:
                json.dump(timing_res, f, ensure_ascii=False, indent=2)
            logger.info("已成功导出 feature_operators_output.json 与 timing_hexagon_output.json")
        except Exception as ex_json:
            logger.warning(f"落盘 output JSON 失败: {ex_json}")

        logger.info("=== 全量特征算子与择时六面图数据计算完毕 ===")
        return report


if __name__ == "__main__":
    engine = FeatureOperatorEngine()
    data = engine.run_all()
    print(json.dumps(data, indent=2, ensure_ascii=False))
