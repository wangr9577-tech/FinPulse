"""
Skill Loader Core Module
========================================================================
负责动态载入 backend/skills 下注册的 Agent Skills 指导规范与启发式规则，
将其无缝注入各 Agent 的系统 Prompt 与推理节点中。
"""
from pathlib import Path
from typing import Dict, Optional
from app.core.logger import app_logger

class SkillLoader:
    """
    Agent Skill 动态加载与管理引擎
    """
    SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

    @classmethod
    def get_skill_path(cls, skill_name: str) -> Path:
        return cls.SKILLS_DIR / skill_name

    @classmethod
    def load_skill_prompt(cls, skill_name: str = "premarket-audio-analysis") -> str:
        """
        装载 Skill 主文档 (SKILL.md) 及其关联的 reference heuristics 规则
        """
        skill_folder = cls.get_skill_path(skill_name)
        skill_md = skill_folder / "SKILL.md"
        heuristics_md = skill_folder / "references" / "heuristics.md"

        prompt_parts = []

        if skill_md.exists():
            content = skill_md.read_text(encoding="utf-8")
            # 过滤 YAML frontmatter
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    content = parts[2].strip()
            prompt_parts.append(f"【挂载 SKILL 指导范式 ({skill_name})】:\n{content}")

        if heuristics_md.exists():
            h_content = heuristics_md.read_text(encoding="utf-8")
            prompt_parts.append(f"【买方启发式推演规则库 (Heuristics)】:\n{h_content}")

        if not prompt_parts:
            app_logger.warning(f"[SkillLoader] 警告：未找到名称为 {skill_name} 的 Skill 配置文件")
            return ""

        full_skill_prompt = "\n\n".join(prompt_parts)
        app_logger.info(f"[SkillLoader] 成功加载 Skill [{skill_name}]，注入字符数: {len(full_skill_prompt)}")
        return full_skill_prompt
