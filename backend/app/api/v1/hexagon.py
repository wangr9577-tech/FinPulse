"""
择时六面图数据接口 (Hexagon Overview Endpoint)
为前端「择时六面图」页面提供：
1. 六面图指标明细 (indicators: 维度/指标名/最新值/信号/生效日期)
2. 维度信号统计 (dimension_counts: 每维度 看多/看空/中性 数量)
3. 全局信号汇总 (bullish/bearish/neutral 信号列表)
4. 雷达图与各指标走势图静态资源 URL 映射
"""
import json
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import APIRouter

from app.core.config import settings
from app.core.logger import app_logger

router = APIRouter(prefix="/hexagon", tags=["Hexagon & Indicators"])

# 静态资源基础 URL (前端通过 /static 访问 backend/output 目录)
STATIC_BASE = "/static"


def _load_json_relative(rel_path: str) -> Dict[str, Any]:
    """读取 output 目录下的 JSON 文件，失败时严格抛错 (Fail-Fast)"""
    target = Path(settings.OUTPUT_DIR) / rel_path
    if not target.exists():
        app_logger.error(f"[Hexagon API] 数据文件不存在: {target}")
        raise FileNotFoundError(f"择时六面图数据文件缺失: {target.name}")
    with open(target, "r", encoding="utf-8") as f:
        return json.load(f)


@router.get("/overview", summary="获取择时六面图指标数据与图表资源映射")
async def get_hexagon_overview():
    # 1. 六面图指标与信号 (顶层直接含 indicators / dimension_counts / 信号列表)
    timing_data = _load_json_relative("timing_hexagon_output.json")

    # 2. 特征算子 (两融 / 宏观流动性 / 估值 / 产业资本)
    feature_data = _load_json_relative("feature_operators_output.json")

    # 3. 扫描 charts 目录生成指标 -> 静态 URL 映射
    charts_dir = settings.OUTPUT_DIR / "charts"
    chart_urls: Dict[str, str] = {}
    radar_url: Optional[str] = None

    if charts_dir.exists():
        radar_png = charts_dir / "Radar_Six_Dimensions.png"
        if radar_png.exists():
            radar_url = f"{STATIC_BASE}/charts/Radar_Six_Dimensions.png"

        indiv_dir = charts_dir / "individual"
        if indiv_dir.exists():
            for png in sorted(indiv_dir.glob("*.png")):
                chart_urls[png.stem] = f"{STATIC_BASE}/charts/individual/{png.name}"

    # 4. 为每个指标匹配走势图 (规范化后精确匹配优先，包含匹配兜底)
    #    文件名形如 "流动性_SHIBOR_1W.png"，指标名形如 "SHIBOR 1W"，
    #    维度名可能与文件前缀不一致 (经济面 vs 宏观经济 / 情绪面 vs 情绪与期权面)，
    #    因此统一去 空格/下划线/横线 后做匹配。
    import re as _re

    def _norm(s: str) -> str:
        return _re.sub(r"[\s_\-（）()]", "", str(s)).lower()

    norm_urls = {_norm(k): v for k, v in chart_urls.items()}

    indicators = timing_data.get("indicators", [])
    for item in indicators:
        ind = item.get("indicator", "")
        dim = item.get("dimension", "")
        norm_ind = _norm(ind)
        norm_dim_ind = _norm(f"{dim}_{ind}")

        matched = (
            norm_urls.get(norm_ind)
            or norm_urls.get(norm_dim_ind)
            or next((v for k, v in norm_urls.items() if norm_ind in k), None)
        )
        item["chart_url"] = matched

    return {
        "code": 200,
        "message": "success",
        "data": {
            "as_of_date": timing_data.get("as_of_date"),
            "total_indicators": timing_data.get("total_indicators", len(indicators)),
            "dimension_scores": timing_data.get("dimension_scores", {}),
            "dimension_details": timing_data.get("dimension_details", {}),
            "dimension_counts": timing_data.get("dimension_counts", {}),
            "bullish_signals": timing_data.get("bullish_signals", []),
            "bearish_signals": timing_data.get("bearish_signals", []),
            "neutral_signals": timing_data.get("neutral_signals", []),
            "indicators": indicators,
            "operators": feature_data.get("operators", {}),
            "radar_chart_url": radar_url,
        },
    }
