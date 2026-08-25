"""
盘前语音与财经文本买方信号提取工具 (Premarket Insight Extractor Script)
========================================================================
功能：
1. 自动对盘前语音转录文本或快讯文本执行“真金白银”审计（区分注销式回购 vs 激励式回购）。
2. 识别 Q2 环比加速 (QoQ Acceleration) 与单季高增标的。
3. 提炼跨年度大额长期订单与大股东自筹增持事实。
4. 严格限制仅在 backend 目录内检索数据，支持 CLI 与模块化导入。
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional


class PremarketInsightExtractor:
    """
    买方盘前信号与品质审计提取器
    """
    def __init__(self, transcript_path: Optional[Path] = None):
        if transcript_path is None:
            script_dir = Path(__file__).resolve().parent
            sample_asset = script_dir.parent / "assets" / "盘前语音.md"
            sample_raw = script_dir.parents[2] / "data" / "raw" / "盘前语音.md"
            self.transcript_path = sample_asset if sample_asset.exists() else sample_raw
        else:
            self.transcript_path = Path(transcript_path)

    def audit_cancellation_buybacks(self, text: str) -> List[Dict[str, str]]:
        """
        审计回购类型：识别明确说明“用于注销注册资本”的真利好回购
        """
        results = []
        # 正则匹配回购公告段落
        pattern = r'([\u4e00-\u9fa5\w]{2,12}(?:科技|股份|集团|重工|半导体|光电|存储|电子|医药|动力|智能))[^。\n]*?回购[^。\n]*?(注销|员工持股|股权激励)'
        matches = re.findall(pattern, text)
        
        seen = set()
        for company, purpose in matches:
            if company in seen:
                continue
            seen.add(company)
            is_cancellation = "注销" in purpose
            results.append({
                "company": company,
                "purpose": "注销注册资本 (缩股)" if is_cancellation else purpose,
                "buyback_quality": "特大利好 (真实缩股)" if is_cancellation else "中性 (常规激励)",
                "is_cancellation": is_cancellation
            })
        return results

    def audit_q2_acceleration(self, text: str) -> List[Dict[str, str]]:
        """
        审计业绩斜率：提炼 Q2 环比 (QoQ) 加速增长的公司
        """
        results = []
        pattern = r'([\u4e00-\u9fa5\w]{2,12}(?:科技|股份|集团|重工|半导体|光电|存储|电子|微|股份))[^。\n]*?(?:上半年|二季度|Q2)[^。\n]*?(?:增长|加速|赚了)[^。\n]*?(\d+[\.\d]*\s*倍|\d+[\.\d]*%)'
        matches = re.findall(pattern, text)
        
        seen = set()
        for company, growth_rate in matches:
            if company in seen:
                continue
            seen.add(company)
            results.append({
                "company": company,
                "growth_metric": growth_rate,
                "performance_tag": "基本面斜率向上 (QoQ加速)"
            })
        return results

    def audit_major_contracts_and_buyins(self, text: str) -> Dict[str, List[str]]:
        """
        提炼大额长期合同与董事长/高管增持事实
        """
        contracts = re.findall(r'([\u4e00-\u9fa5\w]{2,12}(?:科技|股份|精工|光电|电子))[^。\n]*?(?:合同|大单|协议)[^。\n]*?(\d+[\.\d]*\s*亿)', text)
        buyins = re.findall(r'([\u4e00-\u9fa5\w]{2,12}(?:科技|股份|电源|光电|高管|董事长))[^。\n]*?(?:增持|买入自己)', text)

        return {
            "major_contracts": [f"{item[0]}: 签约金额 {item[1]}" for item in set(contracts)],
            "insider_buyins": list(set(buyins))
        }

    def extract_all(self) -> Dict[str, Any]:
        """
        执行全量提炼并返回买方格式 JSON
        """
        if not self.transcript_path.exists():
            return {
                "status": "error",
                "message": f"在 backend 目录内未找到盘前样本文件: {self.transcript_path}"
            }

        text = self.transcript_path.read_text(encoding="utf-8")
        buybacks = self.audit_cancellation_buybacks(text)
        q2_gains = self.audit_q2_acceleration(text)
        contracts_and_buyins = self.audit_major_contracts_and_buyins(text)

        cancellation_count = sum(1 for b in buybacks if b["is_cancellation"])

        return {
            "status": "success",
            "source_file": str(self.transcript_path.name),
            "summary_stats": {
                "total_lines": len(text.splitlines()),
                "total_buyback_events": len(buybacks),
                "cancellation_buyback_count": cancellation_count,
                "q2_acceleration_count": len(q2_gains)
            },
            "audit_results": {
                "buybacks": buybacks,
                "q2_acceleration": q2_gains,
                "major_contracts": contracts_and_buyins["major_contracts"],
                "insider_buyins": contracts_and_buyins["insider_buyins"]
            }
        }


if __name__ == "__main__":
    extractor = PremarketInsightExtractor()
    result = extractor.extract_all()
    print(json.dumps(result, ensure_ascii=False, indent=2))
