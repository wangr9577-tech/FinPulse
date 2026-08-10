# -*- coding: utf-8 -*-
"""
择时六面图 — 自动化指标折线图 + 六维度汇总图 + 六维雷达图 绘图引擎 (app/timing_hexagon/plotter.py)
用于为端到端研报生成 35 项量化指标的高清可视化图表并整合至 PDF 报告中。
"""

import warnings
warnings.filterwarnings('ignore')

import logging
logging.getLogger('matplotlib').setLevel(logging.ERROR)
logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)

import os
from pathlib import Path
from collections import OrderedDict
from typing import Dict, Any, List, Tuple, Optional

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.dates as mdates
from matplotlib.dates import DateFormatter, AutoDateLocator
from scipy.interpolate import make_interp_spline

from app.core.config import settings
from app.core.logger import app_logger

# ========== 全局绘图参数与主题 ==========
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans', 'Arial']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 150
plt.rcParams['savefig.dpi'] = 150
plt.rcParams['savefig.bbox'] = 'tight'

COLOR_PALETTE = ['#E63946', '#2A9D8F', '#457B9D', '#F4A261', '#9B5DE5', '#00B4D8', '#E76F51', '#264653']
CSI800_COLOR = '#1A1A2E'
CSI800_LINEWIDTH = 1.5
INDICATOR_LINEWIDTH = 1.8
BENCHMARK_LINEWIDTH = 1.2
CHART_FIGSIZE = (14, 6)
BULL_COLOR = '#FFD8C0'   # 肉色（看多/上行）
BEAR_COLOR = '#B5E8B5'   # 浅绿（看空/下行）


# ========== 路径配置 ==========
BASE_DATA_DIR = settings.BASE_DIR / "data"
RESULTS_DIR = BASE_DATA_DIR / "results"
CLEAN_DIR = BASE_DATA_DIR / "cleaned_data"
INDICATOR_DIR = RESULTS_DIR / "indicator_outputs"
PROXY_DIR = RESULTS_DIR / "proxy_outputs"
SUMMARY_CSV = RESULTS_DIR / "最新信号汇总.csv"
CSI800_PATH = CLEAN_DIR / "中证800日行情_清洗后.csv"

OUTPUT_CHARTS_DIR = settings.OUTPUT_DIR / "charts"


def _get_csi800_data() -> pd.DataFrame:
    """读取中证800基准行情数据"""
    if not CSI800_PATH.exists():
        return pd.DataFrame(columns=["date", "csi800_close"])
    df = pd.read_csv(CSI800_PATH, encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date")
    df = df.rename(columns={"close": "csi800_close"})
    return df[["date", "csi800_close"]]


def smooth_line(dates, values, num_points=500):
    """三次样条平滑"""
    if len(dates) < 4:
        return dates, values
    x = mdates.date2num(dates)
    x_smooth = np.linspace(x.min(), x.max(), num_points)
    try:
        spl = make_interp_spline(x, values, k=3)
        y_smooth = spl(x_smooth)
        dates_smooth = mdates.num2date(x_smooth)
        return dates_smooth, y_smooth
    except Exception:
        return dates, values


def get_trend_periods(df, date_col, signal_col, use_bull_alignment=False):
    """提取看多/看空区间"""
    if not signal_col or signal_col not in df.columns:
        return [], []

    sub = df.dropna(subset=[date_col, signal_col]).sort_values(date_col).copy()
    if len(sub) == 0:
        return [], []

    dates = sub[date_col].values
    scores = sub[signal_col].values

    bull_ranges = []
    bear_ranges = []

    i = 0
    n = len(scores)
    while i < n:
        curr = scores[i]
        if use_bull_alignment:
            is_bull = (curr == 1)
            start = dates[i]
            while i < n and (scores[i] == 1) == is_bull:
                i += 1
            end = dates[i - 1]
            if is_bull:
                bull_ranges.append((start, end))
            else:
                bear_ranges.append((start, end))
        else:
            if curr > 0:
                start = dates[i]
                while i < n and scores[i] > 0:
                    i += 1
                end = dates[i - 1]
                bull_ranges.append((start, end))
            elif curr < 0:
                start = dates[i]
                while i < n and scores[i] < 0:
                    i += 1
                end = dates[i - 1]
                bear_ranges.append((start, end))
            else:
                i += 1

    return bull_ranges, bear_ranges


def add_trend_background(ax, bull_ranges, bear_ranges):
    """在图表中绘制趋势背景色"""
    for start, end in bull_ranges:
        ax.axvspan(start, end, facecolor=BULL_COLOR, alpha=0.35, zorder=0, linewidth=0)
    for start, end in bear_ranges:
        ax.axvspan(start, end, facecolor=BEAR_COLOR, alpha=0.35, zorder=0, linewidth=0)


def add_benchmark_lines(ax, lines_cfg):
    """在轴上添加基准参考线"""
    for bl in lines_cfg:
        ax.axhline(
            y=bl["value"],
            color=bl.get("color", "#888888"),
            linestyle=bl.get("style", "--"),
            linewidth=BENCHMARK_LINEWIDTH,
            alpha=0.7,
            zorder=3
        )


def _build_indicators_config() -> OrderedDict:
    """定义 35 项择时指标与数据配置"""
    return OrderedDict({
        "流动性": OrderedDict({
            "SHIBOR 1W": {
                "file": INDICATOR_DIR / "01_SHIBOR_1W信号_日度.csv",
                "date_col": "date",
                "value_cols": ["shibor_1w_pct", "ma60"],
                "value_labels": ["SHIBOR 1W (%)", "MA60"],
                "signal_col": "signal_score",
                "title": "SHIBOR 1W — 短端利率与 MA60",
                "ylabel": "利率 (%)",
                "benchmark_lines": []
            },
            "DR007偏离度": {
                "file": PROXY_DIR / "P01_DR007水平代理_日度.csv",
                "date_col": "date",
                "value_cols": ["dr007", "ma60"],
                "value_labels": ["DR007 (%)", "MA60"],
                "signal_col": "signal_score",
                "title": "DR007 偏离度 — 资金利率状态",
                "ylabel": "利率 (%)",
                "benchmark_lines": []
            },
            "M1同比": {
                "file": INDICATOR_DIR / "02_M1同比趋势_月度.csv",
                "date_col": "date",
                "value_cols": ["m1_yoy_pct", "ma6", "ma12"],
                "value_labels": ["M1同比 (%)", "MA6", "MA12"],
                "signal_col": "signal_score",
                "title": "M1同比 — 货币供应趋势",
                "ylabel": "同比 (%)",
                "benchmark_lines": []
            },
            "M1同比-PPI同比": {
                "file": INDICATOR_DIR / "03_M1减PPI趋势_月度.csv",
                "date_col": "date",
                "value_cols": ["m1_minus_ppi_pct_point", "ma6", "ma12"],
                "value_labels": ["M1-PPI (百分点)", "MA6", "MA12"],
                "signal_col": "signal_score",
                "title": "M1同比-PPI同比 — 剪刀差趋势",
                "ylabel": "百分点",
                "benchmark_lines": []
            },
            "M2同比-名义GDP": {
                "file": INDICATOR_DIR / "04_M2减名义GDP_月度.csv",
                "date_col": "date",
                "value_cols": ["m2_minus_nominal_gdp_pct_point"],
                "value_labels": ["M2-名义GDP (百分点)"],
                "signal_col": "signal_score",
                "title": "M2同比-名义GDP增速 — 货币超经济增速",
                "ylabel": "百分点",
                "benchmark_lines": [{"value": 0, "label": "零轴", "color": "#888888", "style": "--"}]
            },
            "信贷脉冲": {
                "file": PROXY_DIR / "P02_信贷脉冲_STL季调代理_月度.csv",
                "date_col": "date",
                "value_cols": ["sa_mom_pct"],
                "value_labels": ["社融季调环比 (%)"],
                "signal_col": "signal_score",
                "title": "信贷脉冲 — 社融季调环比",
                "ylabel": "环比 (%)",
                "benchmark_lines": [
                    {"value": 5, "label": "+5% 触发线", "color": "#E63946", "style": "--"},
                    {"value": 0, "label": "零轴", "color": "#888888", "style": "-"}
                ]
            }
        }),
        "宏观经济": OrderedDict({
            "制造业PMI": {
                "file": INDICATOR_DIR / "05_制造业PMI趋势_月度.csv",
                "date_col": "date",
                "value_cols": ["manufacturing_pmi", "ma6", "ma12"],
                "value_labels": ["制造业PMI", "MA6", "MA12"],
                "signal_col": "signal_score",
                "title": "制造业 PMI — 景气趋势",
                "ylabel": "PMI",
                "benchmark_lines": [{"value": 50, "label": "荣枯线 50", "color": "#888888", "style": "--"}]
            },
            "发电量同比": {
                "file": PROXY_DIR / "P03_全社会用电量同比趋势代理_月度.csv",
                "date_col": "date",
                "value_cols": ["electricity_consumption_yoy_pct", "ma6", "ma12"],
                "value_labels": ["用电量同比 (%)", "MA6", "MA12"],
                "signal_col": "signal_score",
                "title": "发电量同比 — 实体经济热度",
                "ylabel": "同比 (%)",
                "benchmark_lines": []
            },
            "CPI同比": {
                "file": INDICATOR_DIR / "06_CPI历史分位信号_月度.csv",
                "date_col": "date",
                "value_cols": ["cpi_yoy_pct", "historical_q10", "historical_q90"],
                "value_labels": ["CPI同比 (%)", "历史10%分位", "历史90%分位"],
                "signal_col": "signal_score",
                "title": "CPI同比 — 通胀分位信号",
                "ylabel": "同比 (%)",
                "benchmark_lines": []
            },
            "PPI同比": {
                "file": INDICATOR_DIR / "07_PPI历史分位信号_月度.csv",
                "date_col": "date",
                "value_cols": ["ppi_yoy_pct", "historical_q10", "historical_q90"],
                "value_labels": ["PPI同比 (%)", "历史10%分位", "历史90%分位"],
                "signal_col": "signal_score",
                "title": "PPI同比 — 工业品价格分位",
                "ylabel": "同比 (%)",
                "benchmark_lines": []
            }
        }),
        "估值": OrderedDict({
            "PE_TTM中位数": {
                "file": INDICATOR_DIR / "08_PE_TTM中位数信号_日度.csv",
                "date_col": "date",
                "value_cols": ["pe_ttm_median"],
                "value_labels": ["PE_TTM中位数 (倍)"],
                "signal_col": "signal_score",
                "title": "中证800 PE_TTM中位数 — 估值底部信号",
                "ylabel": "PE (倍)",
                "benchmark_lines": [{"value": 20, "label": "20倍 (看多阈值)", "color": "#E63946", "style": "--"}]
            },
            "中证800 PB": {
                "file": INDICATOR_DIR / "09_PB信号_日度.csv",
                "date_col": "date",
                "value_cols": ["pb_index"],
                "value_labels": ["PB (倍)"],
                "signal_col": "signal_score",
                "title": "中证800 PB — 市净率底部信号",
                "ylabel": "PB (倍)",
                "benchmark_lines": [{"value": 1.4, "label": "1.4倍 (看多阈值)", "color": "#E63946", "style": "--"}]
            },
            "股权风险溢价": {
                "file": INDICATOR_DIR / "10_股权风险溢价_日度.csv",
                "date_col": "date",
                "value_cols": ["erp_z5y", "erp_ratio"],
                "value_labels": ["ERP Z-score (5年)", "ERP比率"],
                "signal_col": "signal_score",
                "title": "股权风险溢价 (ERP) — 股债性价比",
                "ylabel": "Z-score / 比率",
                "benchmark_lines": [
                    {"value": 1.5, "label": "+1.5σ (看多)", "color": "#FFD8C0", "style": "--"},
                    {"value": -1.5, "label": "-1.5σ (看空)", "color": "#B5E8B5", "style": "--"}
                ]
            }
        }),
        "资金面": OrderedDict({
            "新增开户数": {
                "file": INDICATOR_DIR / "11_新增开户数反转预警_月度.csv",
                "date_col": "date",
                "value_cols": ["new_investors_10k"],
                "value_labels": ["新增投资者 (万户)"],
                "signal_col": "signal_score",
                "title": "A股新增开户数 — 市场热度预警",
                "ylabel": "万户",
                "benchmark_lines": []
            },
            "北向资金": {
                "file": INDICATOR_DIR / "12_北向资金状态_日度.csv",
                "date_col": "date",
                "value_cols": ["northbound_net_buy_100m"],
                "value_labels": ["北向净买入 (百万元)"],
                "signal_col": "signal_score",
                "title": "北向资金 — 外资流向状态",
                "ylabel": "百万元",
                "benchmark_lines": [{"value": 0, "label": "零轴", "color": "#888888", "style": "-"}]
            },
            "融资融券余额": {
                "file": PROXY_DIR / "P05_融资融券余额趋势_MA60_MA120_日度.csv",
                "date_col": "date",
                "value_cols": ["margin_total", "ma60", "ma120"],
                "value_labels": ["两融余额 (元)", "MA60", "MA120"],
                "signal_col": "signal_score",
                "title": "融资融券余额 — 杠杆资金趋势",
                "ylabel": "余额 (元)",
                "benchmark_lines": []
            }
        }),
        "技术面": OrderedDict({
            "均线排列": {
                "file": INDICATOR_DIR / "13_均线排列_日度.csv",
                "date_col": "date",
                "value_cols": ["close", "ma10", "ma30", "ma60"],
                "value_labels": ["收盘价", "MA10", "MA30", "MA60"],
                "signal_col": "signal_score",
                "title": "均线排列 — 多头/空头排列 (MA10/30/60)",
                "ylabel": "点数",
                "benchmark_lines": [],
                "use_bull_alignment_bg": True
            },
            "均线距离": {
                "file": PROXY_DIR / "P06_均线距离_MA10_MA60_日度.csv",
                "date_col": "date",
                "value_cols": ["distance_pct"],
                "value_labels": ["MA10/MA60-1 (%)"],
                "signal_col": "signal_score",
                "title": "均线距离 — 短长均线偏离 (MA10 vs MA60)",
                "ylabel": "偏离 (%)",
                "benchmark_lines": [
                    {"value": 3, "label": "+3% 上行趋势", "color": "#FFD8C0", "style": "--"},
                    {"value": -3, "label": "-3% 下行趋势", "color": "#B5E8B5", "style": "--"},
                    {"value": 0, "label": "零轴", "color": "#888888", "style": "-"}
                ]
            },
            "RSI": {
                "file": PROXY_DIR / "P14_RSI_Wilder状态_日度.csv",
                "date_col": "date",
                "value_cols": ["rsi6", "rsi24"],
                "value_labels": ["RSI6 (快线)", "RSI24 (慢线)"],
                "signal_col": "signal_score",
                "title": "RSI — Wilder 平滑双线系统",
                "ylabel": "RSI",
                "benchmark_lines": [
                    {"value": 80, "label": "超买 80", "color": "#E63946", "style": "--"},
                    {"value": 20, "label": "超卖 20", "color": "#2A9D8F", "style": "--"}
                ]
            }
        }),
        "情绪与期权面": OrderedDict({
            "成交热度": {
                "file": PROXY_DIR / "P09_成交热度_中证800成交额代理_日度.csv",
                "date_col": "date",
                "value_cols": ["heat_z5y"],
                "value_labels": ["成交热度 Z-score (5年)"],
                "signal_col": "signal_score",
                "title": "成交热度 — 市场交投情绪",
                "ylabel": "Z-score",
                "benchmark_lines": [
                    {"value": 1, "label": "过热 +1σ", "color": "#E63946", "style": "--"},
                    {"value": -1, "label": "过冷 -1σ", "color": "#2A9D8F", "style": "--"}
                ]
            },
            "行业分歧度": {
                "file": PROXY_DIR / "P10_行业分歧度代理_日度.csv",
                "date_col": "date",
                "value_cols": ["z5y"],
                "value_labels": ["分歧度 Z-score (5年)"],
                "signal_col": "signal_score",
                "title": "行业分歧度 — 情绪一致/分化",
                "ylabel": "Z-score",
                "benchmark_lines": [
                    {"value": 1, "label": "过热 +1σ", "color": "#E63946", "style": "--"},
                    {"value": -1, "label": "过冷 -1σ", "color": "#2A9D8F", "style": "--"}
                ]
            },
            "50ETF期权VIX": {
                "file": PROXY_DIR / "P12_50ETF_QVIX信号_日度.csv",
                "date_col": "date",
                "value_cols": ["qvix_z5y"],
                "value_labels": ["QVIX Z-score (5年)"],
                "signal_col": "signal_score",
                "title": "50ETF QVIX — 期权恐慌指数",
                "ylabel": "Z-score",
                "benchmark_lines": [
                    {"value": 1, "label": "恐慌 +1σ (反向看多)", "color": "#E63946", "style": "--"},
                    {"value": -1, "label": "平静 -1σ", "color": "#2A9D8F", "style": "--"}
                ]
            }
        })
    })


def plot_single_indicator_chart(dim_name: str, ind_name: str, cfg: Dict[str, Any], csi_df: pd.DataFrame) -> Optional[Path]:
    """绘制单指标折线图并保存为 PNG 图像"""
    csv_file = Path(cfg["file"])
    if not csv_file.exists():
        return None

    try:
        df = pd.read_csv(csv_file, encoding="utf-8-sig")
        df["date"] = pd.to_datetime(df[cfg["date_col"]], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date")
        if len(df) == 0:
            return None

        if csi_df is not None and not csi_df.empty:
            df = pd.merge(df, csi_df, on="date", how="left")
        else:
            df["csi800_close"] = np.nan

        dates = df["date"].values
        if len(dates) == 0:
            return None

        fig, ax1 = plt.subplots(figsize=CHART_FIGSIZE)
        use_bull_bg = cfg.get("use_bull_alignment_bg", False)

        # 趋势背景
        bull_ranges, bear_ranges = get_trend_periods(
            df, "date", cfg.get("signal_col"), use_bull_alignment=use_bull_bg
        )
        add_trend_background(ax1, bull_ranges, bear_ranges)

        # 左轴：中证800
        csi_close = df["csi800_close"].values
        valid_csi = ~np.isnan(csi_close)
        if valid_csi.sum() >= 2:
            s_dates, s_vals = smooth_line(dates[valid_csi], csi_close[valid_csi])
            ax1.plot(
                s_dates, s_vals, color=CSI800_COLOR, linewidth=CSI800_LINEWIDTH,
                linestyle='--', alpha=0.85, label='中证800 收盘价 (左轴)'
            )
        ax1.set_ylabel("中证800 收盘价", fontsize=11, color=CSI800_COLOR)
        ax1.tick_params(axis='y', labelcolor=CSI800_COLOR)
        ax1.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f'{x:,.0f}'))

        # 右轴：指标数据
        ax2 = ax1.twinx()
        lines_right = []
        for i, (col, label) in enumerate(zip(cfg["value_cols"], cfg["value_labels"])):
            if col in df.columns:
                vals = pd.to_numeric(df[col], errors="coerce").values
                valid = ~np.isnan(vals)
                if valid.sum() >= 2:
                    s_dates, s_vals = smooth_line(dates[valid], vals[valid])
                    color = COLOR_PALETTE[i % len(COLOR_PALETTE)]
                    line, = ax2.plot(
                        s_dates, s_vals, color=color, linewidth=INDICATOR_LINEWIDTH,
                        alpha=0.92, label=label
                    )
                    lines_right.append(line)

        ax2.set_ylabel(cfg.get("ylabel", "数值"), fontsize=11)
        ax2.grid(True, alpha=0.25, linewidth=0.5)

        if cfg.get("benchmark_lines"):
            add_benchmark_lines(ax2, cfg["benchmark_lines"])

        ax1.xaxis.set_major_formatter(DateFormatter('%Y'))
        ax1.xaxis.set_major_locator(AutoDateLocator())
        ax1.set_xlim(dates.min(), dates.max())
        ax1.set_title(f"{dim_name}维度 — {cfg['title']}", fontsize=14, fontweight='bold', pad=12)

        # 顶部图例
        all_lines = list(ax1.lines) + lines_right
        seen = set()
        unique_lines = []
        for l in all_lines:
            lbl = l.get_label()
            if lbl and lbl not in seen:
                seen.add(lbl)
                unique_lines.append(l)

        if unique_lines:
            leg = fig.legend(
                handles=unique_lines, loc='upper center',
                bbox_to_anchor=(0.5, 0.98), ncol=min(len(unique_lines), 5),
                fontsize=9, frameon=True, framealpha=0.85, edgecolor='#cccccc'
            )
            leg.get_frame().set_linewidth(0.5)

        fig.tight_layout(rect=[0, 0, 1, 0.92])

        # 保存图片
        save_dir = OUTPUT_CHARTS_DIR / "individual"
        save_dir.mkdir(parents=True, exist_ok=True)
        safe_name = ind_name.replace("/", "_").replace("-", "_").replace(" ", "_")
        img_path = save_dir / f"{dim_name}_{safe_name}.png"
        fig.savefig(img_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        return img_path

    except Exception as e:
        app_logger.error(f"[Plotter Engine] 绘制指标图表失败 [{dim_name} - {ind_name}]: {e}")
        return None


# ========== 维度加权得分计算 ==========
# 六面图维度名映射（CSV 维度 → 报告标准名）
DIMENSION_MAP = OrderedDict([
    ("流动性", "流动性"),
    ("经济面", "宏观经济"),
    ("估值面", "估值"),
    ("资金面", "资金面"),
    ("技术面", "技术面"),
    ("情绪面", "情绪与期权面"),
])
# 不参与加权统计的指标（数据独立性不足，不得与同维度重复计分）
EXCLUDED_WEIGHTED_INDICATORS = {"DR007偏离度"}


def compute_dimension_weighted_scores(summary_csv_path: Path) -> OrderedDict:
    """按维度计算加权得分：看多=+1 / 看空=-1 / 中性=0 的非空信号均值。"""
    scores = OrderedDict((name, 0.0) for name in DIMENSION_MAP.values())
    if not Path(summary_csv_path).exists():
        return scores
    try:
        summary = pd.read_csv(summary_csv_path, encoding="utf-8-sig")
        for csv_dim, display_name in DIMENSION_MAP.items():
            sub = summary[
                (summary["dimension"] == csv_dim)
                & (summary["signal_score"].notna())
                & (~summary["indicator"].isin(EXCLUDED_WEIGHTED_INDICATORS))
            ]
            if len(sub) > 0:
                scores[display_name] = float(sub["signal_score"].mean())
    except Exception as e:
        app_logger.error(f"[Plotter Engine] 计算维度加权得分失败: {e}")
    return scores


def format_score_value(value: float) -> str:
    """格式化得分值：正数带 + 号，保留两位小数。"""
    if value > 0:
        return f"+{value:.2f}"
    return f"{value:.2f}"


def score_direction(value: float) -> str:
    """按得分符号给出方向标签。"""
    if value > 0:
        return "看多"
    if value < 0:
        return "看空"
    return "中性"


def format_weighted_score_line(scores: OrderedDict) -> str:
    """生成研报第二章维度加权得分一行文字。"""
    return " | ".join(
        f"{dim} {format_score_value(v)} [{score_direction(v)}]"
        for dim, v in scores.items()
    )


def plot_radar_chart(summary_csv_path: Path) -> Optional[Path]:
    """绘制择时六维度合规雷达图（维度加权得分 = 各维度看多/看空/中性信号均值）"""
    if not summary_csv_path.exists():
        return None
    try:
        dimension_scores = compute_dimension_weighted_scores(summary_csv_path)
        labels = list(dimension_scores.keys())
        n = len(labels)
        angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
        angles += angles[:1]

        fig, ax = plt.subplots(figsize=(7, 7), subplot_kw={'polar': True})
        usable_values = [dimension_scores[d] for d in labels]
        usable_values += usable_values[:1]

        ax.fill(angles, usable_values, color='#457B9D', alpha=0.25)
        ax.plot(angles, usable_values, color='#457B9D', linewidth=2.5,
                marker='o', markersize=9, label='维度加权得分')

        neutral_values = [0] * (n + 1)
        ax.plot(angles, neutral_values, color='#888888', linewidth=1.5,
                linestyle='--', alpha=0.7, label='中性水平 (0)')

        # 每面顶点标注得分值
        for angle, val in zip(angles[:-1], dimension_scores.values()):
            ax.annotate(
                format_score_value(val), xy=(angle, val),
                xytext=(angle, val + 0.15), ha='center', va='bottom',
                fontsize=11, fontweight='bold', color='#1A1A2E'
            )

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(labels, fontsize=11, fontweight='bold')
        ax.set_ylim(-1.5, 1.5)
        ax.set_yticks([-1.0, -0.5, 0, 0.5, 1.0])
        ax.set_yticklabels(['-1.0', '-0.5', '0', '+0.5', '+1.0'], fontsize=8)
        ax.set_title("择时六面图 — 维度综合信号雷达图", fontsize=14, fontweight='bold', pad=20)
        ax.legend(loc='upper right', bbox_to_anchor=(1.25, 1.1), fontsize=9)

        img_path = OUTPUT_CHARTS_DIR / "Radar_Six_Dimensions.png"
        OUTPUT_CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        fig.savefig(img_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        return img_path

    except Exception as e:
        app_logger.error(f"[Plotter Engine] 绘制六维雷达图失败: {e}")
        return None


def generate_all_hexagon_charts() -> Dict[str, str]:
    """
    生成择时六面图全部高清图表（单指标折线图 + 六维雷达图）
    返回格式：{ "流动性_SHIBOR 1W": "file:///path/to/img.png", ... }
    """
    app_logger.info("[Plotter Engine] 启动择时 35 项指标高清图表渲染引擎...")
    csi_df = _get_csi800_data()
    indicators_cfg = _build_indicators_config()

    chart_paths_map = {}
    success_count = 0

    for dim_name, ind_dict in indicators_cfg.items():
        for ind_name, cfg in ind_dict.items():
            img_path = plot_single_indicator_chart(dim_name, ind_name, cfg, csi_df)
            if img_path and img_path.exists():
                file_uri = img_path.as_uri()
                chart_paths_map[f"{dim_name}_{ind_name}"] = file_uri
                chart_paths_map[ind_name] = file_uri
                success_count += 1

    # 绘制雷达图
    radar_path = plot_radar_chart(SUMMARY_CSV)
    if radar_path and radar_path.exists():
        chart_paths_map["RADAR_CHART"] = radar_path.as_uri()

    app_logger.info(f"[Plotter Engine] 成功渲染完成 {success_count} 张指标折线图与雷达图！输出目录: {OUTPUT_CHARTS_DIR}")
    return chart_paths_map
