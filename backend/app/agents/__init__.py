"""
Multi-Agent Package
包含 Extractor Agent (信息抽取), Tagger Agent (打标分类), Analyst Agent (板块分析), Synthesizer Agent (报告合成), Auditor Agent (风控审查)
"""
from .extractor_agent import ExtractorAgent, ExtractionResult
from .tagger_agent import TaggerAgent, TaggingResult
from .analyst_agent import AnalystAgent, SectorAnalysisResult
from .synthesizer_agent import SynthesizerAgent, SynthesizedReportResult
from .auditor_agent import AuditorAgent, AuditResult

__all__ = [
    "ExtractorAgent",
    "ExtractionResult",
    "TaggerAgent",
    "TaggingResult",
    "AnalystAgent",
    "SectorAnalysisResult",
    "SynthesizerAgent",
    "SynthesizedReportResult",
    "AuditorAgent",
    "AuditResult",
]
