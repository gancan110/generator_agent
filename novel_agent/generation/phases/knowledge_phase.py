"""
知识准备阶段执行器

负责知识采集和世界观生成。
"""

import logging
from typing import Dict

from .context import PipelineContext

logger = logging.getLogger(__name__)


class KnowledgePhase:
    """
    知识准备阶段
    
    执行流程：
    1. 采集类型相关知识（文化、写作技法等）
    2. 生成小说世界观（力量体系、势力分布等）
    3. 将知识存入向量存储供后续检索
    """

    def __init__(self, ctx: PipelineContext):
        self.ctx = ctx

    def run(self) -> Dict[str, str]:
        """
        执行知识准备阶段
        
        Returns:
            knowledge: 包含世界观等知识的字典
        """
        logger.info("=== 阶段 1: 知识采集 ===")
        knowledge = self._collect_knowledge()
        
        logger.info("=== 阶段 2: 世界观生成 ===")
        self._generate_worldview(knowledge)
        
        return knowledge

    def restore_from_db(self) -> Dict[str, str]:
        """
        从数据库恢复知识（用于 resume 模式）
        
        Returns:
            knowledge: 恢复的知识字典
        """
        logger.info("从数据库恢复知识上下文...")
        knowledge = {}
        
        if not self.ctx.knowledge_base:
            return knowledge
        
        # 从 world_settings 表读取已存储的知识
        world_settings = self.ctx.knowledge_base.get_all_world_settings()
        for setting in world_settings:
            knowledge[setting.category] = setting.content
        
        logger.info(f"已恢复 {len(knowledge)} 条知识记录")
        return knowledge

    def rebuild_vector_store(self, knowledge: Dict[str, str], existing_chapters: list = None):
        """
        重建向量存储（用于 resume 模式）
        
        Args:
            knowledge: 知识字典
            existing_chapters: 已生成的章节列表
        """
        if not self.ctx.vector_store:
            return
        
        # 如果向量存储已有数据，跳过重建
        if self.ctx.vector_store.document_count > 0:
            logger.info(f"向量存储已有 {self.ctx.vector_store.document_count} 条记录，跳过重建")
            return
        
        logger.info("重建向量存储...")
        
        # 添加知识到向量存储
        for category, content in knowledge.items():
            if content:
                self.ctx.vector_store.add_documents(
                    [content],
                    source_type="knowledge",
                    metadata={"category": category}
                )
        
        # 添加已有章节内容
        if existing_chapters:
            for chapter in existing_chapters:
                if chapter.content:
                    self.ctx.vector_store.add_documents(
                        [chapter.content],
                        source_type="chapter",
                        metadata={
                            "chapter_number": chapter.chapter_number,
                            "title": chapter.title
                        }
                    )
        
        logger.info(f"向量存储重建完成，共 {self.ctx.vector_store.document_count} 条记录")

    def _collect_knowledge(self) -> Dict[str, str]:
        """采集类型相关知识"""
        if not self.ctx.knowledge_collector:
            logger.warning("知识采集器未初始化，跳过知识采集")
            return {}
        
        skill = self.ctx.skill_context
        knowledge = self.ctx.knowledge_collector.collect(
            genre=skill.genre if skill else "",
            theme=skill.theme if skill else "",
        )
        
        # 存入知识库
        if self.ctx.knowledge_base:
            for category, content in knowledge.items():
                if content:
                    self.ctx.knowledge_base.upsert_world_setting(category, content)
        
        # 存入向量存储
        if self.ctx.vector_store and knowledge:
            for category, content in knowledge.items():
                if content:
                    self.ctx.vector_store.add_documents(
                        [content],
                        source_type="knowledge",
                        metadata={"category": category}
                    )
        
        logger.info(f"知识采集完成，共 {len(knowledge)} 个类别")
        return knowledge

    def _generate_worldview(self, knowledge: Dict[str, str]):
        """生成小说世界观"""
        if not self.ctx.knowledge_base:
            logger.warning("知识库未初始化，跳过世界观生成")
            return
        
        worldview = self.ctx.knowledge_base.generate_novel_worldview(
            genre=self.ctx.skill_context.genre if self.ctx.skill_context else "",
            theme=self.ctx.skill_context.theme if self.ctx.skill_context else "",
        )
        
        # 将世界观存入知识库
        for category, content in worldview.items():
            if content:
                self.ctx.knowledge_base.upsert_world_setting(category, content)
                # 同时存入向量存储
                if self.ctx.vector_store:
                    self.ctx.vector_store.add_documents(
                        [content],
                        source_type="worldview",
                        metadata={"category": category}
                    )
        
        logger.info("世界观生成完成")
