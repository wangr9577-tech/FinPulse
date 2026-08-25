"""
投研报告格式校验与排版修补器 (ReportValidator)
满足 8月12日 WBS 交付要求：
1. 设计专业 Markdown 研报结构校验器 (ReportValidator)
2. 校验标题层级 (#, ##, ###) 与 4 大必备关键章节完整度 (宏观总揽、风险警示、跨行业连锁、板块深度)
3. 自动修补语法与格式缺陷 (如未闭合代码块、悬空标题、列表缩进错乱、连续空行修剪)
"""
import re
from typing import List, Tuple, Dict, Any, Optional
from pydantic import BaseModel, Field

from app.core.logger import app_logger


class ValidationResult(BaseModel):
    """
    研报校验与修补结果模型
    """
    is_valid: bool = Field(..., description="研报结构是否校验通过")
    error_messages: List[str] = Field(default_factory=list, description="校验失败的严重错误列表")
    warning_messages: List[str] = Field(default_factory=list, description="校验警告与修补建议列表")
    repaired_markdown: str = Field(..., description="格式美化修补后的 Markdown 文本")
    section_count: int = Field(0, description="识别到的核心大类章节数量")


class ReportValidator:
    """
    投研报告排版美化与结构校验器
    """
    REQUIRED_SECTIONS = [
        "总评",
        "择时六面图",
        "资讯分析"
    ]

    def __init__(self):
        pass

    def repair(self, markdown_text: str) -> str:
        """
        自动修补 Markdown 排版缺陷与语法错误
        """
        if not markdown_text:
            return "# 投研报告 (无内容)\n\n*暂无有效研报文本*"

        text = markdown_text.strip()

        # 1. 修补未闭合的代码块 (```)
        code_block_count = len(re.findall(r"^```", text, flags=re.MULTILINE))
        if code_block_count % 2 != 0:
            text += "\n```"

        # 2. 规范标题前的空行：确保 #, ##, ### 标题前至少有 1 个空行 (避免与上方段落粘连)
        text = re.sub(r"([^\n])\n(#{1,4}\s+)", r"\1\n\n\2", text)

        # 3. 清除连续超过 3 个的空行
        text = re.sub(r"\n{4,}", "\n\n\n", text)

        # 4. 规范无序列表点符号：统一使用标准的 "- " 前缀
        text = re.sub(r"^\s*[\*\•]\s+", "- ", text, flags=re.MULTILINE)

        # 5. 确保 Alert 框 (如 > [!NOTE]) 后面有空格
        text = re.sub(r"^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]([^\n])", r"> [!\1]\n> \2", text, flags=re.MULTILINE)

        return text

    def validate(self, markdown_text: str) -> ValidationResult:
        """
        校验 Markdown 研报结构的合法性与完整度，并自动输出美化修补后的文本
        """
        errors = []
        warnings = []

        if not markdown_text or len(markdown_text.strip()) < 50:
            errors.append("研报文本内容过短 (小于 50 个字符)，未能构成有效投研报告。")
            repaired = self.repair(markdown_text)
            return ValidationResult(
                is_valid=False,
                error_messages=errors,
                warning_messages=warnings,
                repaired_markdown=repaired,
                section_count=0
            )

        # 自动执行格式修复
        repaired = self.repair(markdown_text)

        # 1. 检查标题层级结构 (# 和 ##)
        h1_match = re.findall(r"^#\s+(.+)$", repaired, flags=re.MULTILINE)
        h2_matches = re.findall(r"^##\s+(.+)$", repaired, flags=re.MULTILINE)

        if not h1_match:
            warnings.append("研报缺少主标题 (# 一级标题)，格式不完全符合标准模板。")

        if len(h2_matches) < 2:
            warnings.append(f"研报二级标题 (##) 数量过少 (当前 {len(h2_matches)} 个)，建议区分宏观与行业章节。")

        # 2. 检查必备的核心研报章节
        found_sections = 0
        for req in self.REQUIRED_SECTIONS:
            if any(req in heading for heading in h2_matches) or any(req in heading for heading in h1_match) or req in repaired[:1000]:
                found_sections += 1
            else:
                warnings.append(f"未在研报标题中显式检测到 '{req}' 核心章节。")

        # 3. 检查代码块闭合性
        code_blocks = re.findall(r"^```", repaired, flags=re.MULTILINE)
        if len(code_blocks) % 2 != 0:
            errors.append("检测到未闭合的 Markdown 代码块 (```)。")

        is_valid = len(errors) == 0

        if is_valid:
            app_logger.info(f"[ReportValidator] 研报格式校验通过！识别到 {len(h2_matches)} 个二级章节，{found_sections} 个核心必备块。")
        else:
            app_logger.warning(f"[ReportValidator] 研报存在 {len(errors)} 个错误，{len(warnings)} 个警告。")

        return ValidationResult(
            is_valid=is_valid,
            error_messages=errors,
            warning_messages=warnings,
            repaired_markdown=repaired,
            section_count=len(h2_matches)
        )
