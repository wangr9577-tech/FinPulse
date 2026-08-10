# 择时六面图维度加权得分雷达图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复并重写 `plot_radar_chart`，用「看多=+1 / 看空=-1 / 中性=0 的维度均值」绘制六面图，并在研报第二章输出一行维度加权得分。

**Architecture:** 在 `app/timing_hexagon/plotter.py` 新增纯函数 `compute_dimension_weighted_scores()`（读 `最新信号汇总.csv`，按维度对 `signal_score` 非空值求均值，排除 DR007），连同格式化辅助函数供雷达图与 `synthesizer_agent` 复用；重写 `plot_radar_chart()` 调用该函数并标注每面得分；在 `synthesizer_agent.py::build_timing_hexagon_markdown_chapter()` 雷达图后插入 `> **维度加权得分**：...` 一行。

**Tech Stack:** Python 3.10+, pandas, matplotlib, 无新依赖。

**口径（已与用户确认）：** 计入全部 `signal_score` 非 NaN 的指标；**排除** `DR007偏离度`（CSV note 注明不独立、不得与 SHIBOR 重复计分）。不可计算（NaN）不计入平均。无有效指标维度回退 0.0。

**维度映射表（CSV 维度 → 六面图标准名）：**
`流动性→流动性`、`经济面→宏观经济`、`估值面→估值`、`资金面→资金面`、`技术面→技术面`、`情绪面→情绪与期权面`

> ⚠️ 数据修正说明：剔除 DR007 后，当前真实 CSV 的流动性加权得分是 **0.00**（此前口径含 DR007 时为 +0.17）。下文 Task 1 测试用合成 CSV 验证逻辑，Task 4 对真实 CSV 输出做人工复核。

---

### Task 1: 新增维度加权得分计算与格式化辅助函数

**Files:**
- Create: `scripts/test/test_dimension_weighted_scores.py`
- Modify: `app/timing_hexagon/plotter.py`（在 `plot_single_indicator_chart` 函数结束之后、`plot_radar_chart` 之前插入）

- [ ] **Step 1: 编写失败测试脚本**

创建 `scripts/test/test_dimension_weighted_scores.py`：

```python
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


if __name__ == "__main__":
    selected = sys.argv[1:] or [
        "test_weighted_scores",
        "test_missing_file_all_zero",
        "test_format_helpers",
        "test_plot_radar_smoke",
        "test_synthesizer_chapter_contains_weighted_line",
    ]
    for name in selected:
        globals()[name]()
        print(f"PASS {name}")
    print("ALL SELECTED TESTS PASSED")
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd "d:/研报/FinPulse" && PYTHONIOENCODING=utf-8 python scripts/test/test_dimension_weighted_scores.py test_weighted_scores`
Expected: FAIL — `ImportError: cannot import name 'compute_dimension_weighted_scores'`

- [ ] **Step 3: 实现辅助函数**

在 `app/timing_hexagon/plotter.py` 的 `plot_single_indicator_chart` 函数结束（第 519 行 `return None` 之后）与 `plot_radar_chart`（第 522 行）之间插入：

```python
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
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd "d:/研报/FinPulse" && PYTHONIOENCODING=utf-8 python scripts/test/test_dimension_weighted_scores.py test_weighted_scores test_missing_file_all_zero test_format_helpers`
Expected: PASS 三行 + `ALL SELECTED TESTS PASSED`

- [ ] **Step 5: 提交**

```bash
git add app/timing_hexagon/plotter.py scripts/test/test_dimension_weighted_scores.py
git commit -m "feat: add dimension weighted score computation for hexagon radar"
```

---

### Task 2: 重写 plot_radar_chart 使用维度加权得分并标注每面得分

**Files:**
- Modify: `app/timing_hexagon/plotter.py`（替换整个 `plot_radar_chart` 函数体，第 522-569 行）

- [ ] **Step 1: 运行冒烟测试，确认当前实现失败**

Run: `cd "d:/研报/FinPulse" && PYTHONIOENCODING=utf-8 python scripts/test/test_dimension_weighted_scores.py test_plot_radar_smoke`
Expected: FAIL — 当前 `plot_radar_chart` 读取 `usable_current_score` 列，合成 CSV 无该列，返回 `None`（断言 `img is not None` 失败）

- [ ] **Step 2: 重写函数**

用以下内容整体替换 `plot_radar_chart`（原第 522-569 行）：

```python
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
```

- [ ] **Step 3: 运行冒烟测试，确认通过**

Run: `cd "d:/研报/FinPulse" && PYTHONIOENCODING=utf-8 python scripts/test/test_dimension_weighted_scores.py test_plot_radar_smoke`
Expected: PASS `test_plot_radar_smoke` + `ALL SELECTED TESTS PASSED`；且 `output/charts/Radar_Six_Dimensions.png` 已生成

- [ ] **Step 4: 提交**

```bash
git add app/timing_hexagon/plotter.py
git commit -m "feat: rewrite radar chart to plot dimension weighted scores"
```

---

### Task 3: 研报第二章插入维度加权得分一行

**Files:**
- Modify: `app/agents/synthesizer_agent.py`（`build_timing_hexagon_markdown_chapter`，第 332-333 行之后）

- [ ] **Step 1: 运行测试，确认当前实现失败**

Run: `cd "d:/研报/FinPulse" && PYTHONIOENCODING=utf-8 python scripts/test/test_dimension_weighted_scores.py test_synthesizer_chapter_contains_weighted_line`
Expected: FAIL — AssertionError: `"维度加权得分" not in md`（当前章节无此行）

- [ ] **Step 2: 实现修改**

在 `build_timing_hexagon_markdown_chapter` 中，雷达图嵌入代码块（`if "RADAR_CHART" in chart_paths_map:` 之后）追加维度加权得分一行。把原文：

```python
    if "RADAR_CHART" in chart_paths_map:
        chapter_intro += f"\n\n![择时六维雷达图]({chart_paths_map['RADAR_CHART']})"
```

替换为：

```python
    if "RADAR_CHART" in chart_paths_map:
        chapter_intro += f"\n\n![择时六维雷达图]({chart_paths_map['RADAR_CHART']})"

    # 维度加权得分一行（紧跟雷达图之后）
    try:
        from app.timing_hexagon.plotter import (
            compute_dimension_weighted_scores,
            format_weighted_score_line,
            SUMMARY_CSV,
        )
        weighted_scores = compute_dimension_weighted_scores(SUMMARY_CSV)
        weighted_line = format_weighted_score_line(weighted_scores)
        chapter_intro += f"\n\n> **维度加权得分**：{weighted_line}"
    except Exception as e:
        app_logger.warning(f"[SynthesizerAgent] 生成维度加权得分一行失败: {e}")
```

- [ ] **Step 3: 运行测试，确认通过**

Run: `cd "d:/研报/FinPulse" && PYTHONIOENCODING=utf-8 python scripts/test/test_dimension_weighted_scores.py test_synthesizer_chapter_contains_weighted_line`
Expected: PASS `test_synthesizer_chapter_contains_weighted_line` + `ALL SELECTED TESTS PASSED`

- [ ] **Step 4: 提交**

```bash
git add app/agents/synthesizer_agent.py
git commit -m "feat: add dimension weighted score line to report chapter 2"
```

---

### Task 4: 对真实 CSV 复核 + 全量回归

- [ ] **Step 1: 打印真实 CSV 的六面加权得分**

Run: `cd "d:/研报/FinPulse" && PYTHONIOENCODING=utf-8 python -c "from app.timing_hexagon.plotter import compute_dimension_weighted_scores, format_weighted_score_line, SUMMARY_CSV; s=compute_dimension_weighted_scores(SUMMARY_CSV); print(format_weighted_score_line(s))"`
Expected: 按当前数据应输出 `流动性 0.00 [中性] | 宏观经济 +0.50 [看多] | 估值 0.00 [中性] | 资金面 +1.00 [看多] | 技术面 -0.14 [看空] | 情绪与期权面 -0.67 [看空]`（若真实数据更新则以 CSV 为准，人工核对合理性）

- [ ] **Step 2: 跑全部测试**

Run: `cd "d:/研报/FinPulse" && PYTHONIOENCODING=utf-8 python scripts/test/test_dimension_weighted_scores.py`
Expected: 5 个 PASS + `ALL SELECTED TESTS PASSED`

- [ ] **Step 3: 提交（如无改动则跳过）**

```bash
git status
```

---

## 验收标准

1. `output/charts/Radar_Six_Dimensions.png` 正确生成，六个维度得分与 `最新信号汇总.csv` 口径一致（排除 DR007、非空均值）。
2. 雷达图每个维度顶点标注得分值，保留 0 轴中性虚线。
3. 研报第二章在雷达图后包含 `> **维度加权得分**：...` 一行，方向标签与每面总结论一致。
4. 所有测试通过，无新依赖。
