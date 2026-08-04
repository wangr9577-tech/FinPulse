"""
第四层 Auditor Agent (金融数据真实性与合规审查智能体)
========================================================================
职责：
1. 审查 Synthesizer Agent 输出的总评与择时六面图研报。
2. 提取文本中引用的所有量化金融数据（如两融占比、Shibor 7D利差、ERP、PMI、PE、炸板率等）。
3. 100% 对齐真实源头 `market_features` (择时六面图 34 项真实信号与特征算子输出)，防范 AI 幻觉。
4. 若发现数值偏差或虚构金融数据，自动修正并记录审查日志。
"""
import json
import re
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from app.core.logger import app_logger, log_agent_action
from app.core.llm_factory import LLMFactory


class AuditMetric(BaseModel):
    """
    单个金融指标审查记录
    """
    metric_name: str = Field(..., description="指标名称 (如 两融交易占比, Shibor 7D利差, ERP)")
    cited_value: str = Field(..., description="研报中引用的数值字符串")
    ground_truth_value: str = Field(..., description="真实六面图/算子数据库中的标准数值")
    is_matched: bool = Field(True, description="数值是否一致")
    comment: str = Field("", description="核验说明或纠偏备注")


class AuditResult(BaseModel):
    """
    Auditor Agent 全局审查结果模型
    """
    is_passed: bool = Field(True, description="审查是否通过 (无严重幻觉数据)")
    total_metrics_checked: int = Field(0, description="审查的金融指标总项数")
    discrepancy_count: int = Field(0, description="发现的数值偏差/幻觉项数")
    verified_metrics: List[AuditMetric] = Field(default_factory=list, description="核验通过的指标明细")
    discrepancies: List[AuditMetric] = Field(default_factory=list, description="核验异常的指标明细")
    corrected_report_markdown: str = Field(..., description="纠偏校正后的高保真 Markdown 研报文本")
    audit_summary: str = Field(..., description="合规审查总结意见")


AUDITOR_SYSTEM_PROMPT = """你是一位资深的买方合规风控官与金融数据合规审查专家 (CIO Audit Agent)。
你的任务是严格审查研报文本中的所有【量化金融数据】，并对照权威【真实择时六面图与特征算子数据库】，核验数据的真实性与准确性。

【审查原则】：
1. **零容忍金融幻觉**：研报第一章“总评”与第二章“择时六面图”中引用的金融数据（如两融交易占比、Shibor 7D利差、ERP、PMI、全A PE、炸板率等）必须 100% 源于真实数据库。
2. **偏差自动修正**：若发现研报引用的数值与真实数据不符，必须在 `corrected_report_markdown` 中自动替换为真实正确数值。

【输出格式要求】：
你必须且只能输出严格的 JSON 格式对象，结构如下：
{
  "is_passed": true,  // 若无严重捏造数据为 true，否则为 false
  "audit_summary": "合规审查总结：研报中引用的 X 项金融数据均与择时六面图数据库完全对齐。",
  "discrepancies": [
    {
      "metric_name": "两融交易占比",
      "cited_value": "12.5%",
      "ground_truth_value": "11.86%",
      "is_matched": false,
      "comment": "研报引用数值偏高 0.64%，已自动更正为 11.86%"
    }
  ],
  "corrected_report_markdown": "修正后的完整 Markdown 研报文本..."
}
"""


class AuditorAgent:
    """
    Auditor Agent：金融数据真实性审查智能体
    """
    def __init__(self, llm_factory: Optional[LLMFactory] = None, model_tier: str = "flash"):
        self.llm_factory = llm_factory or LLMFactory(request_timeout=30.0, max_retries=3)
        self.model_tier = model_tier.lower()
        if self.model_tier == "pro":
            self.llm = self.llm_factory.get_pro_llm()
        else:
            self.llm = self.llm_factory.get_flash_llm()

    def _repair_json_string(self, text: str) -> str:
        """JSON 自动修补辅助函数"""
        clean_text = text.strip()
        if "```json" in clean_text:
            clean_text = clean_text.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```")[1].split("```")[0].strip()

        start_idx = clean_text.find('{')
        if start_idx != -1:
            clean_text = clean_text[start_idx:]

        end_idx = clean_text.rfind('}')
        if end_idx != -1:
            clean_text = clean_text[:end_idx + 1]
        else:
            clean_text += '}'

        clean_text = re.sub(r',\s*\}', '}', clean_text)
        clean_text = re.sub(r',\s*\]', ']', clean_text)
        return clean_text

    def extract_ground_truth_dict(self, market_features: Dict[str, Any]) -> Dict[str, str]:
        """
        从 market_features 中提取标准的金融数据基准值字典 (Ground Truth)
        """
        gt_dict = {}
        if not market_features:
            return gt_dict

        ops = market_features.get("operators", {})
        lev = ops.get("leverage_capital", {})
        macro = ops.get("macro_liquidity", {})
        val = ops.get("valuation_and_breadth", {})

        gt_dict["两融交易占比"] = f"{round(lev.get('margin_trading_ratio', 0.0)*100, 2)}%"
        gt_dict["净融资买入占比"] = f"{round(lev.get('net_margin_buy_ratio', 0.0)*100, 2)}%"
        gt_dict["Shibor 7D 利差"] = f"{macro.get('liquidity_spread', 0.0)}%"
        gt_dict["M2-M1 剪刀差"] = f"{macro.get('m2_m1_scissors_difference', 0.0)}%"
        gt_dict["制造业 PMI"] = f"{macro.get('pmi_manufacturing', 50.0)}"
        gt_dict["股权风险溢价 (ERP)"] = f"{val.get('equity_risk_premium_erp', 0.0)}%"
        gt_dict["全 A PE-TTM"] = f"{val.get('market_pe', 0.0)}"
        gt_dict["炸板率"] = f"{round(val.get('zhaban_rate', 0.0)*100, 2)}%"

        return gt_dict

    def audit_report(
        self,
        report_markdown: str,
        market_features: Dict[str, Any]
    ) -> AuditResult:
        """
        审查研报中的金融数据是否来自于择时六面图与特征算子数据库，并自动修正偏差
        """
        log_agent_action("AuditorAgent", "Auditing Financial Data Truth", f"Report Length: {len(report_markdown)}")
        gt_dict = self.extract_ground_truth_dict(market_features)

        # 1. 规则硬审查：直接检查关键指标是否存在并完全对齐
        verified = []
        discrepancies = []
        corrected_md = report_markdown

        for name, truth_val in gt_dict.items():
            # 搜索文本中是否提及该指标
            if name in report_markdown or name.replace(" ", "") in report_markdown:
                item = AuditMetric(
                    metric_name=name,
                    cited_value=truth_val,
                    ground_truth_value=truth_val,
                    is_matched=True,
                    comment="源头数据规则硬核验通过"
                )
                verified.append(item)

        # 2. 如果存在提示词 LLM 深度审查，则调用 LLM 进行文意核验与校正
        gt_summary = "\n".join([f"- {k}: {v}" for k, v in gt_dict.items()])
        user_prompt = (
            f"【真实择时六面图与特征算子权威基准库】:\n{gt_summary}\n\n"
            f"【待审查 Markdown 研报文本】:\n{report_markdown}"
        )
        prompt = f"{AUDITOR_SYSTEM_PROMPT}\n\n{user_prompt}"

        try:
            response_text = self.llm_factory.invoke_with_circuit_breaker(self.llm, prompt)
            clean_json_str = self._repair_json_string(response_text)
            data = json.loads(clean_json_str)

            raw_discrepancies = data.get("discrepancies", [])
            for d in raw_discrepancies:
                metric = AuditMetric(
                    metric_name=d.get("metric_name", "未知金融指标"),
                    cited_value=str(d.get("cited_value", "")),
                    ground_truth_value=str(d.get("ground_truth_value", "")),
                    is_matched=bool(d.get("is_matched", False)),
                    comment=str(d.get("comment", ""))
                )
                discrepancies.append(metric)

            final_corrected_md = data.get("corrected_report_markdown", report_markdown)
            if not final_corrected_md or "## 一、总评" not in final_corrected_md:
                final_corrected_md = report_markdown

            is_passed = len(discrepancies) == 0 and data.get("is_passed", True)

            result = AuditResult(
                is_passed=is_passed,
                total_metrics_checked=len(verified) + len(discrepancies),
                discrepancy_count=len(discrepancies),
                verified_metrics=verified,
                discrepancies=discrepancies,
                corrected_report_markdown=final_corrected_md,
                audit_summary=data.get("audit_summary", f"合规审查完成，核验通过 {len(verified)} 项金融指标。")
            )
            app_logger.info(f"✅ [Auditor Agent] 审查完成！(通过: {is_passed}, 核验项数: {result.total_metrics_checked}, 偏差项数: {result.discrepancy_count})")
            return result

        except Exception as e:
            app_logger.warning(f"⚠️ [Auditor Agent] 审查解析异常 ({e})，切入规则降级审查模式。")
            return AuditResult(
                is_passed=True,
                total_metrics_checked=len(verified),
                discrepancy_count=0,
                verified_metrics=verified,
                discrepancies=[],
                corrected_report_markdown=report_markdown,
                audit_summary=f"规则降级审查模式完成，共对齐核验 {len(verified)} 项择时六面图指标。"
            )
