# 择时六面图 — 维度加权得分雷达图 设计文档

> 日期：2026-08-10
> 状态：已确认

## 背景与问题

项目已具备 `data/results/最新信号汇总.csv`（由 `app/timing_hexagon/02_指标计算.py` 生成），
每行一个指标，`signal_score` 已是离散多空信号：看多=+1、看空=-1、中性=0（NaN 表示不可计算）。

当前问题：
1. `app/timing_hexagon/plotter.py::plot_radar_chart()` 存在维度名匹配 bug：
   雷达图用 `["流动性","宏观经济","估值","资金面","技术面","情绪与期权面"]` 的 `dim[:2]` 去
   匹配 CSV 中的维度，而 CSV 实际维度为 `["流动性","经济面","估值面","资金面","技术面","情绪面"]`，
   导致「宏观经济」维度永远匹配不到、得分恒为 0。
2. 该函数使用 `usable_current_score`（仅 aggregation_eligible 且未过期的子集）求平均，
   资金面/情绪面几乎没有有效值，雷达图整体偏向 0，无法反映真实多空。
3. `output/` 下没有生成任何 charts 目录，六面图从未真正产出，研报中看不到。

## 需求

对每个维度：看多=+1、看空=-1、中性=0，对该维度下所有有明确结论的指标（signal_score 非 NaN）
计算平均值为**维度加权得分**，以六边形雷达图形式展现。

## 决策口径（已与用户确认）

- **计入范围**：全部 `signal_score` 非 NaN 的指标；**排除** `DR007偏离度`
  （CSV note 注明其不独立、不得与 SHIBOR 重复计分）。
- **展示方式**：雷达图 + 研报第二章一行维度加权得分文字。

## 修改内容

### 1. `app/timing_hexagon/plotter.py`

新增可复用函数：

```python
def compute_dimension_weighted_scores(summary_csv: Path) -> OrderedDict
```

- 维度映射（CSV 维度 → 六面图标准名）：
  - `流动性 → 流动性`
  - `经济面 → 宏观经济`
  - `估值面 → 估值`
  - `资金面 → 资金面`
  - `技术面 → 技术面`
  - `情绪面 → 情绪与期权面`
- 得分 = 该维度下 `signal_score` 非 NaN 且 `indicator != "DR007偏离度"` 的均值。
- 无有效指标时回退为 0.0。

重写 `plot_radar_chart()`：

- 调用 `compute_dimension_weighted_scores(SUMMARY_CSV)`。
- 六边形雷达图：填充 + 折线（沿用现有配色 `#457B9D`）、0 轴中性虚线参考、
  每个维度顶点标注得分值、y 轴范围 -1.5 ~ 1.5。
- 保存 `output/charts/Radar_Six_Dimensions.png`。
- `generate_all_hexagon_charts()` 返回的 `RADAR_CHART` 键保持不变。

### 2. `app/agents/synthesizer_agent.py`

`build_timing_hexagon_markdown_chapter()`：

- 第二章引言末尾、雷达图图片之后、各维度小节之前，插入一行维度加权得分：
  `> **维度加权得分**：流动性 +0.17 [看多] | 宏观经济 +0.50 [看多] | 估值 0.00 [中性] | 资金面 +1.00 [看多] | 技术面 -0.14 [看空] | 情绪与期权面 -0.67 [看空]`
- 数值来自 `compute_dimension_weighted_scores()`，方向标签按得分符号：
  >0 看多、<0 看空、=0 中性。
- 格式化：正数带 `+` 号，保留两位小数。

## 不做的事

- 不改动 `02_指标计算.py`（信号数据已完备）。
- 不改动研报第三章、总评章节。
- 不引入新依赖（沿用 matplotlib）。

## 验收标准

- `output/charts/Radar_Six_Dimensions.png` 正确生成，六个维度得分与
  `最新信号汇总.csv` 按口径计算一致。
- 研报第二章包含雷达图与维度加权得分一行。
- 回归：`plot_radar_chart` 对空文件/缺维度等边界不抛异常。
