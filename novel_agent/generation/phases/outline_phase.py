"""
大纲阶段执行器

负责小说大纲的生成和周期性更新。
"""

import logging
from typing import Dict, List, Optional

from .context import PipelineContext

logger = logging.getLogger(__name__)


class OutlinePhase:
    """
    大纲阶段
    
    执行流程：
    1. 生成初始大纲（章节规划）
    2. 在主循环中周期性更新大纲
    """

    def __init__(self, ctx: PipelineContext):
        self.ctx = ctx

    def generate_initial_outline(self, knowledge: Dict[str, str]) -> Dict:
        """
        生成初始大纲
        
        Args:
            knowledge: 知识字典（包含世界观等）
            
        Returns:
            outline: 生成的大纲字典
        """
        logger.info("=== 阶段 3: 初始大纲生成 ===")
        
        if not self.ctx.outline_generator:
            logger.warning("大纲生成器未初始化，使用默认大纲")
            return {"chapters": []}
        
        # 构建知识上下文
        knowledge_context = self._build_knowledge_context(knowledge)
        
        # 生成大纲
        outline = self.ctx.outline_generator.generate_initial_outline(
            knowledge_context=knowledge_context,
            target_chapters=self.ctx.config.generation.default_chapters
            if self.ctx.config else 100,
        )
        
        self.ctx.current_outline = outline
        logger.info(f"初始大纲生成完成，共 {len(outline.get('chapters', []))} 章")
        return outline

    def update_outline(
        self,
        current_chapter: int,
        recent_summaries: str,
        knowledge_context: Dict[str, str],
    ) -> Optional[Dict]:
        """
        周期性更新大纲
        
        Args:
            current_chapter: 当前章节号
            recent_summaries: 最近章节摘要
            knowledge_context: 知识上下文
            
        Returns:
            更新后的大纲，如果不需要更新则返回 None
        """
        if not self.ctx.outline_updater:
            return None
        
        # 检查是否需要更新
        update_interval = (
            self.ctx.config.generation.outline_update_interval
            if self.ctx.config else 5
        )
        if current_chapter % update_interval != 0:
            return None
        
        logger.info(f"第 {current_chapter} 章：更新大纲...")
        
        updated_outline = self.ctx.outline_updater.update_outline(
            current_chapter=current_chapter,
            recent_chapters_summary=recent_summaries,
            knowledge_context=knowledge_context,
        )
        
        if updated_outline:
            self.ctx.current_outline = updated_outline
            logger.info("大纲更新完成")
        
        return updated_outline

    def _build_knowledge_context(self, knowledge: Dict[str, str]) -> Dict[str, str]:
        """构建大纲生成所需的知识上下文"""
        context = {}
        
        if not self.ctx.knowledge_base:
            return context
        
        # 从知识库获取各类信息
        world_setting = self.ctx.knowledge_base.get_world_setting("world_setting")
        background = self.ctx.knowledge_base.get_world_setting("background")
        power_system = self.ctx.knowledge_base.get_world_setting("power_system")
        factions = self.ctx.knowledge_base.get_world_setting("factions")
        
        if world_setting:
            context["world_setting"] = world_setting[:2000]
        if background:
            context["background"] = background[:2000]
        if power_system:
            context["power_system"] = power_system[:2000]
        if factions:
            context["factions"] = factions[:2000]
        
        # 添加写作技法和风格
        writing_techniques = self.ctx.knowledge_base.get_world_setting("writing_techniques")
        style = self.ctx.knowledge_base.get_world_setting("style")
        if writing_techniques:
            context["writing_techniques"] = writing_techniques[:1000]
        if style:
            context["style"] = style[:1000]
        
        return context
