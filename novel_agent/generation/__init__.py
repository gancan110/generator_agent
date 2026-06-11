"""核心生成模块"""

from novel_agent.generation.pipeline import GenerationPipeline
from novel_agent.generation.chapter_generator import ChapterGenerator

__all__ = ["GenerationPipeline", "ChapterGenerator"]
