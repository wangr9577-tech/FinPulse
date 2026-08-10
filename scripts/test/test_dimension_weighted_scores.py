# -*- coding: utf-8 -*-
"""
维度加权得分计算与雷达图冒烟测试
验证 plotter.compute_dimension_weighted_scores 的维度映射、DR007 排除、NaN 处理，
以及 format_weighted_score_line 输出与 plot_radar_chart 冒烟。
用法：python scripts/test/test_dimension_weighted_scores.py [test函数名 ...]
"""
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.timing_hexagon.plotter import (
    compute_dimension_weighted_scores,
    format_score_value,
    score_direction,
    format_weighted_score_line,
    plot_radar_chart,
)

CSV_CONTENT = (
    "dimension,indicator,signal_score\n"
    "流动性,SHIBOR 1W,1\n"
    "流动性,DR007偏离度,1\n"
    "流动性,M1同比,-1\n"
    "流动性,M1同比-PPI同比,-1\n"
    "流动性,M2同比-名义GDP增速,1\n"
    "流动性,信贷脉冲,0\n"
    "经济面,制造业PMI,1\n"
    "经济面,发电量同比,1\n"
    "经济面,CPI同比,0\n"
    "经济面,PPI同比,0\n"
    "估值面,中证800 PB,0\n"
    "估值面,中证800股权风险溢价,0\n"
    "估值面,中证800 DCF估值,\n"
    "资金面,融资融券余额,1\n"
    "技术面,均线排列,0\n"
    "技术面,均线距离,-1\n"
    "技术面,布林带,0\n"
    "技术面,RSI,-1\n"
    "技术面,250日新高占比,0\n"
    "技术面,250日新低占比,0\n"
    "技术面,成交额+波动率时钟,1\n"
    "情绪面,成交热度,-1\n"
    "情绪面,行业分歧度,-1\n"
    "情绪面,偏股基金仓位,0\n"
)


def _write_temp_csv(content: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", encoding="utf-8-sig", delete=False
    )
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


def test_weighted_scores():
    path = _write_temp_csv(CSV_CONTENT)
    scores = compute_dimension_weighted_scores(path)
    assert list(scores.keys()) == ["流动性", "宏观经济", "估值", "资金面", "技术面", "情绪与期权面"], scores
    # 排除 DR007 后：流动性 [1,-1,-1,1,0] 均值 0.0
    assert abs(scores["流动性"] - 0.0) < 1e-9, scores
    assert abs(scores["宏观经济"] - 0.5) < 1e-9, scores
    assert abs(scores["估值"] - 0.0) < 1e-9, scores
    assert abs(scores["资金面"] - 1.0) < 1e-9, scores
    assert abs(scores["技术面"] - (-1 / 7)) < 1e-9, scores
    assert abs(scores["情绪与期权面"] - (-2 / 3)) < 1e-9, scores
    path.unlink()


def test_missing_file_all_zero():
    scores = compute_dimension_weighted_scores(Path("不存在的文件.csv"))
    assert all(v == 0.0 for v in scores.values()), scores
    assert list(scores.keys()) == ["流动性", "宏观经济", "估值", "资金面", "技术面", "情绪与期权面"]


def test_format_helpers():
    assert format_score_value(0.5) == "+0.50"
    assert format_score_value(-0.142857) == "-0.14"
    assert format_score_value(0.0) == "0.00"
    assert score_direction(0.5) == "看多"
    assert score_direction(-0.1) == "看空"
    assert score_direction(0.0) == "中性"
    line = format_weighted_score_line({"流动性": 0.0, "技术面": -1 / 7, "经济面": 0.5})
    assert line == "流动性 0.00 [中性] | 技术面 -0.14 [看空] | 经济面 +0.50 [看多]", line


def test_plot_radar_smoke():
    assert plot_radar_chart(Path("不存在的文件.csv")) is None
    path = _write_temp_csv(CSV_CONTENT)
    img = plot_radar_chart(path)
    assert img is not None and img.exists() and img.stat().st_size > 0, img
    path.unlink()


class _StubLLMFactory:
    """占位工厂：构造不抛错，但调用即抛，促使 _generate_dimension_summaries 走默认兜底分支。"""
    def get_llm(self):
        raise RuntimeError("stub llm")

    def invoke_with_circuit_breaker(self, llm, prompt):
        raise RuntimeError("stub llm")


def test_synthesizer_chapter_contains_weighted_line():
    from app.agents.synthesizer_agent import build_timing_hexagon_markdown_chapter
    md = build_timing_hexagon_markdown_chapter(
        timing_data={"timing_hexagon": {"indicators": []}, "operators": {}},
        hours_back=24.0,
        llm_factory=_StubLLMFactory(),
        chart_paths_map={},
    )
    assert "维度加权得分" in md, md[:500]


def test_synthesizer_chapter_with_real_indicators():
    """用真实最新信号汇总 CSV 的指标列表构建第二章，覆盖 _format_val 的 pd.isna 路径。"""
    import pandas as pd
    from app.timing_hexagon.plotter import SUMMARY_CSV
    from app.agents.synthesizer_agent import build_timing_hexagon_markdown_chapter

    df = pd.read_csv(SUMMARY_CSV, encoding="utf-8-sig")
    indicators = []
    for _, row in df.iterrows():
        score = row.get("signal_score")
        indicators.append({
            "dimension": str(row.get("dimension", "")),
            "indicator": str(row.get("indicator", "")),
            "latest_value": None if pd.isna(row.get("latest_value")) else row.get("latest_value"),
            "signal_score": float(score) if pd.notna(score) else None,
            "signal_text": str(row.get("signal_text", "")),
        })
    assert len(indicators) > 0
    md = build_timing_hexagon_markdown_chapter(
        timing_data={"timing_hexagon": {"indicators": indicators}, "operators": {}},
        hours_back=24.0,
        llm_factory=_StubLLMFactory(),
        chart_paths_map={},
    )
    assert "维度加权得分" in md, md[:500]
    assert "**流动性**" not in md  # 占位符不应用于真实指标
    assert any("结论" in line for line in md.splitlines()), md[:500]


if __name__ == "__main__":
    selected = sys.argv[1:] or [
        "test_weighted_scores",
        "test_missing_file_all_zero",
        "test_format_helpers",
        "test_plot_radar_smoke",
        "test_synthesizer_chapter_contains_weighted_line",
        "test_synthesizer_chapter_with_real_indicators",
    ]
    for name in selected:
        globals()[name]()
        print(f"PASS {name}")
    print("ALL SELECTED TESTS PASSED")
