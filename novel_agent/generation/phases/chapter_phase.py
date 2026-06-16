"""
章节生成阶段执行器

负责逐章生成小说内容的主循环。
"""

import logging
from typing import Dict, List, Optional

from novel_agent.database.mysql_client import db_client
from novel_agent.database.models import Chapter
from novel_agent.core.events import event_bus, EventType

from .context import PipelineContext

logger = logging.getLogger(__name__)


class ChapterGenerationPhase:
    """
    章节生成阶段
    
    执行流程（每章）：
    1. 构建上下文（记忆 + 知识 + 大纲）
    2. 生成章节内容
    3. 后处理（向量化、资产更新、悬念管理）
    4. 质量评估与重写
    5. 周期性维护（大纲更新、记忆压缩）
    """

    def __init__(self, ctx: PipelineContext):
        self.ctx = ctx

    def run(
        self,
        knowledge: Dict[str, str],
        from_chapter: int = 1,
        target_chapter: int = None,
    ):
        """
        执行章节生成主循环
        
        Args:
            knowledge: 知识字典
            from_chapter: 起始章节号
            target_chapter: 目标章节号
        """
        if target_chapter is None:
            target_chapter = (
                self.ctx.config.generation.default_chapters
                if self.ctx.config else 100
            )
        
        logger.info(f"=== 阶段 4: 章节生成 (第 {from_chapter}-{target_chapter} 章) ===")
        
        # 构建知识上下文（静态部分）
        knowledge_context = self._build_knowledge_context(knowledge)
        
        for chapter_num in range(from_chapter, target_chapter + 1):
            self._generate_single_chapter(
                chapter_num=chapter_num,
                knowledge=knowledge,
                knowledge_context=knowledge_context,
            )
        
        logger.info(f"章节生成完成，共生成 {target_chapter - from_chapter + 1} 章")

    def _generate_single_chapter(
        self,
        chapter_num: int,
        knowledge: Dict[str, str],
        knowledge_context: Dict[str, str],
    ):
        """生成单个章节"""
        logger.info(f"\n{'='*60}")
        logger.info(f"生成第 {chapter_num} 章")
        logger.info(f"{'='*60}")
        
        # 发布章节开始事件
        event_bus.emit(EventType.CHAPTER_STARTED, {
            "chapter_number": chapter_num,
            "project_id": self.ctx.project_id,
        })
        
        # 1. 获取当前大纲
        chapter_outline = self._get_chapter_outline(chapter_num)
        
        # 2. 获取悬念信息
        pending_suspense = self._get_pending_suspense()
        
        # 3. 构建记忆上下文
        memory_context = self._build_memory_context(
            chapter_num, chapter_outline, pending_suspense
        )
        
        # 4. 获取前章信息
        prev_summary = self._get_previous_chapter_summary(chapter_num)
        prev_tail = self._get_previous_chapter_tail(chapter_num)
        
        # 5. 构建资产上下文
        asset_context = self._build_asset_context(chapter_num)
        
        # 6. 构建完整上下文
        full_context = {
            **knowledge_context,
            **memory_context,
            "前章摘要": prev_summary,
            "前章结尾": prev_tail,
            **asset_context,
        }
        
        # 7. 生成章节内容
        chapter_data = self._generate_chapter_content(
            chapter_num, chapter_outline, full_context
        )
        
        # 8. 后处理
        self._post_process_chapter(chapter_num, chapter_data)
        
        # 9. 质量评估与重写
        self._evaluate_and_rewrite(chapter_num, chapter_data, knowledge_context)
        
        # 10. 周期性维护
        self._periodic_maintenance(
            chapter_num, knowledge, knowledge_context
        )
        
        # 发布章节完成事件
        event_bus.emit(EventType.CHAPTER_COMPLETED, {
            "chapter_number": chapter_num,
            "project_id": self.ctx.project_id,
            "title": chapter_data.get("title", ""),
            "word_count": chapter_data.get("word_count", 0),
        })

    def _get_chapter_outline(self, chapter_num: int) -> str:
        """获取指定章节的大纲"""
        if not self.ctx.current_outline:
            return ""
        
        chapters = self.ctx.current_outline.get("chapters", [])
        for ch in chapters:
            if ch.get("chapter_number") == chapter_num:
                return f"第{chapter_num}章: {ch.get('title', '')}\n{ch.get('summary', '')}"
        
        return f"第{chapter_num}章"

    def _get_pending_suspense(self) -> List[Dict]:
        """获取待解决的悬念"""
        if not self.ctx.suspense_manager:
            return []
        return self.ctx.suspense_manager.get_pending_suspense()

    def _build_memory_context(
        self,
        chapter_num: int,
        chapter_outline: str,
        pending_suspense: List[Dict],
    ) -> Dict:
        """构建记忆上下文"""
        if not self.ctx.memory_manager:
            return {}
        
        return self.ctx.memory_manager.build_full_context(
            chapter_number=chapter_num,
            chapter_outline=chapter_outline,
            pending_suspense=pending_suspense,
        )

    def _get_previous_chapter_summary(self, chapter_num: int) -> str:
        """获取前一章摘要"""
        if chapter_num <= 1:
            return ""
        
        prev_chapter = db_client.get_chapter_by_number(
            self.ctx.project_id, chapter_num - 1
        )
        return prev_chapter.summary if prev_chapter else ""

    def _get_previous_chapter_tail(self, chapter_num: int, tail_length: int = 500) -> str:
        """获取前一章结尾"""
        if chapter_num <= 1:
            return ""
        
        prev_chapter = db_client.get_chapter_by_number(
            self.ctx.project_id, chapter_num - 1
        )
        if prev_chapter and prev_chapter.content:
            return prev_chapter.content[-tail_length:]
        return ""

    def _build_asset_context(self, chapter_num: int) -> Dict:
        """构建资产上下文"""
        context = {}
        
        if self.ctx.character_manager:
            context["活跃角色"] = self.ctx.character_manager.get_summary()
        
        if self.ctx.item_manager:
            context["重要物品"] = self.ctx.item_manager.get_summary()
        
        if self.ctx.world_setting_manager:
            context["世界设定"] = self.ctx.world_setting_manager.get_summary()
        
        if self.ctx.suspense_manager:
            context["当前悬念"] = str(
                self.ctx.suspense_manager.get_pending_suspense()
            )
        
        return context

    def _build_knowledge_context(self, knowledge: Dict[str, str]) -> Dict[str, str]:
        """构建知识上下文"""
        context = {}
        
        if not self.ctx.knowledge_base:
            return context
        
        for category in [
            "world_setting", "background", "power_system", "factions",
            "writing_techniques", "style"
        ]:
            content = self.ctx.knowledge_base.get_world_setting(category)
            if content:
                context[category] = content[:2000]
        
        return context

    def _generate_chapter_content(
        self,
        chapter_num: int,
        chapter_outline: str,
        context: Dict,
    ) -> Dict:
        """生成章节内容"""
        if not self.ctx.chapter_generator:
            logger.error("章节生成器未初始化")
            return {}
        
        return self.ctx.chapter_generator.generate_chapter(
            chapter_number=chapter_num,
            chapter_outline=chapter_outline,
            context=context,
        )

    def _post_process_chapter(self, chapter_num: int, chapter_data: Dict):
        """章节后处理"""
        content = chapter_data.get("content", "")
        if not content:
            return
        
        # 1. 添加到向量存储
        if self.ctx.vector_store:
            self.ctx.vector_store.add_documents(
                [content],
                source_type="chapter",
                metadata={
                    "chapter_number": chapter_num,
                    "title": chapter_data.get("title", ""),
                },
            )
        
        # 2. 更新角色和物品
        self._update_plot_assets(chapter_data)
        
        # 3. 处理悬念
        if self.ctx.suspense_manager:
            self.ctx.suspense_manager.process_chapter_suspense(
                chapter_number=chapter_num,
                content=content,
            )
        
        # 4. 更新记忆时间线
        if self.ctx.memory_manager:
            self.ctx.memory_manager.append_timeline(
                chapter_number=chapter_num,
                summary=chapter_data.get("summary", ""),
            )
        
        # 5. 保存到数据库
        self._save_chapter_to_db(chapter_num, chapter_data)
        
        # 6. 保存到文件
        self._save_chapter_to_file(chapter_num, chapter_data)

    def _update_plot_assets(self, chapter_data: Dict):
        """更新剧情资产（角色、物品等）"""
        content = chapter_data.get("content", "")
        chapter_num = chapter_data.get("chapter_number", 0)
        
        # 确保角色存在
        if self.ctx.character_manager:
            characters = chapter_data.get("characters", [])
            for char_name in characters:
                self.ctx.character_manager.ensure_character(char_name)
            
            # 批量更新角色信息
            self.ctx.character_manager.batch_update_from_chapter(
                chapter_number=chapter_num,
                content=content,
            )
        
        # 提取物品
        if self.ctx.item_manager:
            self.ctx.item_manager.extract_items_from_chapter(
                chapter_number=chapter_num,
                content=content,
            )
            
            # 定期检查物品膨胀
            if chapter_num % 10 == 0:
                self.ctx.item_manager.prevent_inflation()

    def _evaluate_and_rewrite(
        self,
        chapter_num: int,
        chapter_data: Dict,
        knowledge_context: Dict,
    ):
        """质量评估与重写"""
        if not self.ctx.quality_evaluator:
            return
        
        content = chapter_data.get("content", "")
        if not content:
            return
        
        # 评估质量
        score, details, issues = self.ctx.quality_evaluator.evaluate(
            content=content,
            chapter_number=chapter_num,
            knowledge_context=knowledge_context,
        )
        
        logger.info(f"第 {chapter_num} 章质量评分: {score:.2f}")
        
        # 发布质量评估事件
        event_bus.emit(EventType.QUALITY_EVALUATED, {
            "chapter_number": chapter_num,
            "score": score,
            "details": details,
        })
        
        # 低分重写
        from novel_agent.evaluation.quality import QualityEvaluator
        if score < QualityEvaluator.REWRITE_THRESHOLD:
            logger.info(f"第 {chapter_num} 章评分低于阈值，触发重写...")
            
            # 发布低分事件
            event_bus.emit(EventType.QUALITY_LOW, {
                "chapter_number": chapter_num,
                "score": score,
                "threshold": QualityEvaluator.REWRITE_THRESHOLD,
            })
            
            self._rewrite_chapter(chapter_num, chapter_data, knowledge_context)

    def _rewrite_chapter(
        self,
        chapter_num: int,
        chapter_data: Dict,
        knowledge_context: Dict,
    ):
        """重写章节"""
        if not self.ctx.chapter_rewriter:
            return
        
        # 执行重写
        rewritten = self.ctx.chapter_rewriter.rewrite(
            chapter_number=chapter_num,
            original_content=chapter_data.get("content", ""),
            knowledge_context=knowledge_context,
        )
        
        if rewritten:
            # 更新向量存储
            if self.ctx.vector_store:
                self.ctx.vector_store.remove_by_chapter(chapter_num)
                self.ctx.vector_store.add_documents(
                    [rewritten],
                    source_type="chapter",
                    metadata={
                        "chapter_number": chapter_num,
                        "title": chapter_data.get("title", ""),
                        "rewritten": True,
                    },
                )
            
            # 重新评估
            if self.ctx.quality_evaluator:
                new_score, _, _ = self.ctx.quality_evaluator.evaluate(
                    content=rewritten,
                    chapter_number=chapter_num,
                    knowledge_context=knowledge_context,
                )
                logger.info(f"重写后评分: {new_score:.2f}")

    def _periodic_maintenance(
        self,
        chapter_num: int,
        knowledge: Dict[str, str],
        knowledge_context: Dict[str, str],
    ):
        """周期性维护"""
        # 每 5 章验证世界设定一致性
        if chapter_num % 5 == 0 and self.ctx.world_setting_manager:
            self.ctx.world_setting_manager.verify_consistency()
        
        # 每 10 章进行记忆维护
        if chapter_num % 10 == 0 and self.ctx.memory_manager:
            self.ctx.memory_manager.periodic_maintenance()
        
        # 周期性更新大纲
        if self.ctx.outline_updater and chapter_num > 1:
            update_interval = (
                self.ctx.config.generation.outline_update_interval
                if self.ctx.config else 5
            )
            if chapter_num % update_interval == 0:
                recent_summaries = self._get_recent_summaries(chapter_num, 5)
                self.ctx.outline_updater.update_outline(
                    current_chapter=chapter_num,
                    recent_chapters_summary=recent_summaries,
                    knowledge_context=knowledge_context,
                )

    def _get_recent_summaries(self, current_chapter: int, count: int = 5) -> str:
        """获取最近章节摘要"""
        chapters = db_client.get_chapters_by_project(
            self.ctx.project_id, limit=count
        )
        
        summaries = []
        for ch in sorted(chapters, key=lambda x: x.chapter_number):
            if ch.chapter_number < current_chapter:
                summaries.append(
                    f"第{ch.chapter_number}章: {ch.summary}"
                )
        
        return "\n".join(summaries[-count:])

    def _save_chapter_to_db(self, chapter_num: int, chapter_data: Dict):
        """保存章节到数据库"""
        from novel_agent.database.models import Chapter
        
        chapter = Chapter(
            project_id=self.ctx.project_id,
            chapter_number=chapter_num,
            title=chapter_data.get("title", f"第{chapter_num}章"),
            content=chapter_data.get("content", ""),
            summary=chapter_data.get("summary", ""),
        )
        db_client.add(chapter)

    def _save_chapter_to_file(self, chapter_num: int, chapter_data: Dict):
        """保存章节到文件"""
        import os
        from pathlib import Path
        
        output_dir = Path(
            self.ctx.config.output_dir if self.ctx.config else "./output"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"chapter_{chapter_num:04d}.txt"
        filepath = output_dir / filename
        
        content = chapter_data.get("content", "")
        title = chapter_data.get("title", f"第{chapter_num}章")
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"第{chapter_num}章 {title}\n\n")
            f.write(content)
        
        logger.info(f"章节已保存到: {filepath}")
