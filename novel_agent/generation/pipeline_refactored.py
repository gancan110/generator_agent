"""
核心生成流水线

重构版：使用独立阶段执行器（KnowledgePhase, OutlinePhase, ChapterGenerationPhase）
将 1053 行的单体类拆分为可独立测试和替换的模块。
"""

import os
import logging
from pathlib import Path
from typing import Dict, Optional

from novel_agent.config import config
from novel_agent.database.mysql_client import db_client
from novel_agent.database.models import Project, Chapter, PlotPoint
from novel_agent.knowledge.collector import KnowledgeCollector
from novel_agent.knowledge.knowledge_base import KnowledgeBase
from novel_agent.knowledge.vector_store import preload_embedding_model
from novel_agent.knowledge.faiss_vector_store import create_vector_store
from novel_agent.outline.generator import OutlineGenerator
from novel_agent.outline.updater import OutlineUpdater
from novel_agent.generation.chapter_generator import ChapterGenerator
from novel_agent.generation.rewriter import ChapterRewriter
from novel_agent.assets.character import CharacterManager
from novel_agent.assets.item import ItemManager
from novel_agent.assets.world_setting import WorldSettingManager
from novel_agent.suspense.manager import SuspenseManager
from novel_agent.evaluation.quality import QualityEvaluator
from novel_agent.evaluation.optimizer import ParameterOptimizer
from novel_agent.skills import SkillRegistry, SkillContext, SkillGenerator
from novel_agent.memory import MemoryManager

from .phases.context import PipelineContext
from .phases.knowledge_phase import KnowledgePhase
from .phases.outline_phase import OutlinePhase
from .phases.chapter_phase import ChapterGenerationPhase

logger = logging.getLogger(__name__)


class GenerationPipeline:
    """
    小说生成流水线（重构版）

    使用独立阶段执行器，职责更清晰：
    - KnowledgePhase: 知识采集与世界观生成
    - OutlinePhase: 大纲生成与管理
    - ChapterGenerationPhase: 章节生成主循环
    """

    def __init__(
        self,
        title: str,
        genre: str,
        theme: str = "",
        target_chapters: int = None,
        skill_id: str = None,
        skip_skill_init: bool = False,
    ):
        """
        Args:
            title: 小说标题
            genre: 小说题材（如"玄幻修仙"、"都市重生"）
            theme: 小说主题
            target_chapters: 目标章节数
            skill_id: Skill标识符（可选，不提供则自动匹配）
            skip_skill_init: 是否跳过 Skill 初始化（resume 场景使用）
        """
        self.title = title
        self.genre = genre
        self.theme = theme or genre
        self.target_chapters = target_chapters or config.generation.default_chapters

        # Skill 匹配
        self.skill_context: Optional[SkillContext] = None
        self._init_skill(skill_id, skip_if_empty_genre=skip_skill_init)

        # 项目信息
        self._project: Optional[Project] = None
        self._current_chapter: int = 0

        # 阶段执行器（延迟初始化）
        self._ctx: Optional[PipelineContext] = None
        self._knowledge_phase: Optional[KnowledgePhase] = None
        self._outline_phase: Optional[OutlinePhase] = None
        self._chapter_phase: Optional[ChapterGenerationPhase] = None

    def _init_skill(self, skill_id: str = None, skip_if_empty_genre: bool = False):
        """初始化 Skill 上下文"""
        if skip_if_empty_genre and not self.genre:
            logger.debug("Skip Skill 初始化（resume 场景）")
            return

        if skill_id is None and config.skill.enable_auto_match:
            SkillRegistry.register_all()
            skill_id = SkillRegistry.match(self.genre)
            if skill_id:
                logger.info(f"自动匹配到预置 Skill: {skill_id}")

        if skill_id is None and config.skill.enable_auto_generate:
            logger.info(f"尝试 LLM 自动生成 Skill（题材: {self.genre}）...")
            generated_id = SkillGenerator.generate(self.genre, self.theme)
            if generated_id:
                skill_id = generated_id
                logger.info(f"LLM 自动生成 Skill 成功: {skill_id}")

        if skill_id is None:
            skill_id = config.skill.fallback_skill_id
            logger.warning(f"未找到匹配的 Skill，使用默认: {skill_id}")

        try:
            self.skill_context = SkillContext(skill_id)
            logger.info(f"已加载 Skill: {skill_id} ({self.skill_context.skill_name})")
        except Exception as e:
            logger.error(f"Skill 加载失败: {e}，使用默认 Skill")
            self.skill_context = SkillContext(config.skill.fallback_skill_id)

    @property
    def project_id(self) -> int:
        if self._project is None:
            raise RuntimeError("项目未初始化，请先调用 initialize()")
        return self._project.id

    def initialize(self):
        """
        初始化流水线

        创建项目记录、初始化数据库、创建子系统实例。
        """
        logger.info(f"=== 初始化项目: {self.title} ({self.genre}) ===")

        # 启动后台模型预加载
        preload_embedding_model()

        # 初始化数据库
        db_client.init_db()

        # 创建项目
        project = Project(
            title=self.title,
            genre=self.genre,
            theme=self.theme,
            target_chapters=self.target_chapters,
            status="initializing",
            skill_id=self.skill_context.skill_id if self.skill_context else None,
        )
        project_id = db_client.add(project)
        self._project = db_client.get_by_id(Project, project_id)

        # 创建输出目录
        output_dir = Path(config.output_dir) / f"{self.title}_{project_id}"
        output_dir.mkdir(parents=True, exist_ok=True)

        # 初始化子系统
        knowledge_base = KnowledgeBase(project_id)
        vector_store = create_vector_store(project_id, use_faiss=True)
        outline_generator = OutlineGenerator(project_id, self.genre, self.theme, self.skill_context)
        outline_updater = OutlineUpdater(project_id)
        chapter_generator = ChapterGenerator(project_id, self.skill_context)
        chapter_rewriter = ChapterRewriter(project_id)
        character_manager = CharacterManager(project_id)
        item_manager = ItemManager(project_id)
        world_setting_manager = WorldSettingManager(project_id)
        suspense_manager = SuspenseManager(project_id)
        quality_evaluator = QualityEvaluator(self.genre)
        parameter_optimizer = ParameterOptimizer()
        memory_manager = MemoryManager(project_id, vector_store)

        # 创建 Pipeline 上下文
        self._ctx = PipelineContext(
            project_id=project_id,
            project_name=self.title,
            knowledge_base=knowledge_base,
            vector_store=vector_store,
            knowledge_collector=KnowledgeCollector(self.genre, self.skill_context),
            outline_generator=outline_generator,
            outline_updater=outline_updater,
            chapter_generator=chapter_generator,
            chapter_rewriter=chapter_rewriter,
            character_manager=character_manager,
            item_manager=item_manager,
            world_setting_manager=world_setting_manager,
            suspense_manager=suspense_manager,
            quality_evaluator=quality_evaluator,
            parameter_optimizer=parameter_optimizer,
            memory_manager=memory_manager,
            skill_context=self.skill_context,
            config=config,
        )

        # 创建阶段执行器
        self._knowledge_phase = KnowledgePhase(self._ctx)
        self._outline_phase = OutlinePhase(self._ctx)
        self._chapter_phase = ChapterGenerationPhase(self._ctx)

        logger.info(f"项目初始化完成，ID={project_id}")

    def run(self):
        """
        运行完整的生成流水线

        这是主入口方法，按顺序执行所有阶段。
        """
        logger.info(f"=== 开始生成小说: {self.title} ===")

        try:
            # 阶段1-2: 知识准备（采集 + 世界观生成）
            knowledge = self._knowledge_phase.run()

            # 阶段3: 生成初始大纲
            self._outline_phase.generate_initial_outline(knowledge)

            # 阶段4: 主循环 - 生成章节
            self._chapter_phase.run(
                knowledge=knowledge,
                from_chapter=1,
                target_chapter=self.target_chapters,
            )

            # 更新项目状态
            self._project.status = "completed"
            db_client.update(self._project)

            logger.info(f"=== 小说生成完成: {self.title} ===")

        except Exception as e:
            logger.error(f"生成流水线异常: {e}", exc_info=True)
            if self._project:
                self._project.status = "error"
                db_client.update(self._project)
            raise

    def resume(
        self,
        project_id: int,
        add_chapters: int = 0,
        from_chapter: int = 0,
    ):
        """
        续写已有项目

        从数据库恢复项目状态，跳过知识采集和世界观生成，
        直接基于已有内容继续生成后续章节。

        Args:
            project_id: 要续写的项目 ID
            add_chapters: 额外增加的章节数（0 = 按原目标续写完）
            from_chapter: 从指定章节开始（0 = 自动检测最后章节+1）

        Raises:
            RuntimeError: 项目不存在或无已有章节
        """
        logger.info(f"=== 续写项目 ID={project_id} ===")

        # 启动后台模型预加载
        preload_embedding_model()

        # 初始化数据库
        db_client.init_db()

        # 1. 加载项目
        project = db_client.get_by_id(Project, project_id)
        if not project:
            raise RuntimeError(f"项目不存在: ID={project_id}")

        self._project = project
        self.title = project.title
        self.genre = project.genre
        self.theme = project.theme or project.genre

        logger.info(f"项目: {project.title} (题材: {project.genre})")

        # 恢复 Skill 上下文
        self._restore_skill_context(project)

        logger.info(f"当前进度: {project.current_chapter}/{project.target_chapters}")

        # 2. 确定续写起始章节
        last_chapter = 0
        existing_chapters = db_client.get_chapters_by_project(project_id, limit=1)
        if existing_chapters:
            last_chapter = existing_chapters[0].chapter_number

        if last_chapter == 0:
            raise RuntimeError(
                f"项目 ID={project_id} 没有已生成的章节，"
                f"请使用 start 命令从头开始生成。"
            )

        if from_chapter > 0:
            if from_chapter > last_chapter + 1:
                raise RuntimeError(
                    f"指定起始章节 {from_chapter} 超出已有范围 "
                    f"(已有到第 {last_chapter} 章)"
                )
            self._current_chapter = from_chapter - 1
        else:
            self._current_chapter = last_chapter

        # 更新目标章节数
        if add_chapters > 0:
            self.target_chapters = project.target_chapters + add_chapters
            project.target_chapters = self.target_chapters
            db_client.update(project)
            logger.info(f"目标章节已更新: {project.target_chapters} -> {self.target_chapters}")
        else:
            self.target_chapters = project.target_chapters

        if self._current_chapter >= self.target_chapters:
            logger.info(
                f"已达到目标章节数 ({self._current_chapter}/{self.target_chapters})，"
                f"无需续写。"
            )
            return

        start_from = self._current_chapter + 1
        remaining = self.target_chapters - self._current_chapter
        logger.info(
            f"将从第 {start_from} 章开始续写，"
            f"还需生成 {remaining} 章 (目标: {self.target_chapters})"
        )

        # 3. 初始化子系统
        self._init_subsystems(project_id)

        # 4. 从 DB 恢复知识上下文
        knowledge = self._knowledge_phase.restore_from_db()

        # 5. 重建向量存储
        self._knowledge_phase.rebuild_vector_store(knowledge, existing_chapters)

        # 6. 生成续写大纲
        logger.info("生成续写大纲...")
        knowledge_context = self._outline_phase._build_knowledge_context(knowledge)
        pending_suspense = self._ctx.suspense_manager.get_pending_suspense()
        recent_summaries = self._chapter_phase._get_recent_summaries(
            self._current_chapter, 3
        )

        updated_outline = self._ctx.outline_updater.update_outline(
            current_chapter=self._current_chapter,
            knowledge_context=knowledge_context,
            pending_suspense=pending_suspense,
            recent_chapters_summary=recent_summaries,
        )
        self._ctx.current_outline = updated_outline

        # 7. 进入主循环
        project.status = "running"
        db_client.update(project)

        logger.info(f"=== 开始续写: {self.title} (从第 {start_from} 章) ===")

        try:
            self._chapter_phase.run(
                knowledge=knowledge,
                from_chapter=start_from,
                target_chapter=self.target_chapters,
            )

            project.status = "completed"
            db_client.update(project)

            logger.info(f"=== 续写完成: {self.title} (当前 {self._current_chapter} 章) ===")

        except Exception as e:
            logger.error(f"续写流水线异常: {e}", exc_info=True)
            project.status = "error"
            db_client.update(project)
            raise

    def _restore_skill_context(self, project: Project):
        """恢复 Skill 上下文"""
        if project.skill_id:
            try:
                self.skill_context = SkillContext(
                    project.skill_id,
                    project.skill_overrides
                )
                logger.info(f"已恢复 Skill: {project.skill_id}")
            except Exception as e:
                logger.warning(f"Skill 恢复失败: {e}，尝试自动匹配...")
                SkillRegistry.register_all()
                matched = SkillRegistry.match(self.genre)
                if matched:
                    self.skill_context = SkillContext(matched)
                    logger.info(f"自动匹配到 Skill: {matched}")
                else:
                    self.skill_context = SkillContext(config.skill.fallback_skill_id)
                    logger.warning("使用默认 Skill")
        else:
            SkillRegistry.register_all()
            matched = SkillRegistry.match(self.genre)
            if matched:
                self.skill_context = SkillContext(matched)
                logger.info(f"自动匹配到 Skill: {matched}")
            else:
                self.skill_context = SkillContext(config.skill.fallback_skill_id)
                logger.info("使用默认 Skill")

    def _init_subsystems(self, project_id: int):
        """初始化子系统（用于 resume 模式）"""
        knowledge_base = KnowledgeBase(project_id)
        vector_store = create_vector_store(project_id, use_faiss=True)
        outline_generator = OutlineGenerator(project_id, self.genre, self.theme, self.skill_context)
        outline_updater = OutlineUpdater(project_id)
        chapter_generator = ChapterGenerator(project_id, self.skill_context)
        chapter_rewriter = ChapterRewriter(project_id)
        character_manager = CharacterManager(project_id)
        item_manager = ItemManager(project_id)
        world_setting_manager = WorldSettingManager(project_id)
        suspense_manager = SuspenseManager(project_id)
        quality_evaluator = QualityEvaluator(self.genre)
        parameter_optimizer = ParameterOptimizer()
        memory_manager = MemoryManager(project_id, vector_store)

        self._ctx = PipelineContext(
            project_id=project_id,
            project_name=self.title,
            knowledge_base=knowledge_base,
            vector_store=vector_store,
            knowledge_collector=KnowledgeCollector(self.genre, self.skill_context),
            outline_generator=outline_generator,
            outline_updater=outline_updater,
            chapter_generator=chapter_generator,
            chapter_rewriter=chapter_rewriter,
            character_manager=character_manager,
            item_manager=item_manager,
            world_setting_manager=world_setting_manager,
            suspense_manager=suspense_manager,
            quality_evaluator=quality_evaluator,
            parameter_optimizer=parameter_optimizer,
            memory_manager=memory_manager,
            skill_context=self.skill_context,
            config=config,
        )

        self._knowledge_phase = KnowledgePhase(self._ctx)
        self._outline_phase = OutlinePhase(self._ctx)
        self._chapter_phase = ChapterGenerationPhase(self._ctx)
