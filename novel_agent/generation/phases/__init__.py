"""
阶段执行器模块

将 Pipeline 拆分为独立的阶段执行器：
- KnowledgePhase: 知识准备
- OutlinePhase: 大纲管理
- ChapterGenerationPhase: 章节生成
"""

from .context import PipelineContext
from .knowledge_phase import KnowledgePhase
from .outline_phase import OutlinePhase
from .chapter_phase import ChapterGenerationPhase

__all__ = [
    "PipelineContext",
    "KnowledgePhase",
    "OutlinePhase",
    "ChapterGenerationPhase",
]
