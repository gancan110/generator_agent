"""
核心生成流水线

串联所有模块，实现从初始化到章节生成的完整工作流：
初始化 → 知识采集 → 世界观生成 → 大纲生成 → 章节生成 → 知识库更新 → 循环
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
from novel_agent.knowledge.vector_store import VectorStore, preload_embedding_model
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

logger = logging.getLogger(__name__)


class GenerationPipeline:
    """
    小说生成流水线

    串联所有子系统，实现全自动的小说生成流程：
    1. 初始化系统
    2. 采集知识
    3. 生成世界观
    4. 生成初始大纲
    5. 循环生成章节（含知识库更新、悬念管理、质量评估）
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
            skip_skill_init: 是否跳过 Skill 初始化（resume 场景使用，Skill 从 DB 恢复）
        """
        self.title = title
        self.genre = genre
        self.theme = theme or genre
        self.target_chapters = target_chapters or config.generation.default_chapters

        # Skill 匹配（resume 场景下跳过，由 resume() 从 DB 恢复）
        self.skill_context: Optional[SkillContext] = None
        self._init_skill(skill_id, skip_if_empty_genre=skip_skill_init)

        # 子系统（延迟初始化）
        self._project: Optional[Project] = None
        self._knowledge_base: Optional[KnowledgeBase] = None
        self._vector_store: Optional[VectorStore] = None
        self._outline_generator: Optional[OutlineGenerator] = None
        self._outline_updater: Optional[OutlineUpdater] = None
        self._chapter_generator: Optional[ChapterGenerator] = None
        self._chapter_rewriter: Optional[ChapterRewriter] = None
        self._character_manager: Optional[CharacterManager] = None
        self._item_manager: Optional[ItemManager] = None
        self._world_setting_manager: Optional[WorldSettingManager] = None
        self._suspense_manager: Optional[SuspenseManager] = None
        self._quality_evaluator: Optional[QualityEvaluator] = None
        self._parameter_optimizer: Optional[ParameterOptimizer] = None
        self._memory_manager: Optional[MemoryManager] = None

        # 运行时状态
        self._current_outline: Dict = {}
        self._current_chapter: int = 0

    def _init_skill(self, skill_id: str = None, skip_if_empty_genre: bool = False):
        """
        初始化 Skill 上下文。
        
        匹配策略（依次降级）：
        1. 使用指定的 skill_id
        2. 从 Registry 自动匹配预置 Skill
        3. 用 LLM 自动生成 Skill（如已开启）
        4. 使用 fallback _base Skill
        
        Args:
            skill_id: 指定要使用的 Skill ID（可选）
            skip_if_empty_genre: 如果为 True 且 genre 为空，则跳过初始化（供 resume 使用）
        """
        # resume 场景下，如果 genre 为空则跳过初始化（resume 会从 DB 恢复）
        if skip_if_empty_genre and not self.genre:
            logger.debug("Skip Skill 初始化（resume 场景，将在 resume() 中恢复）")
            return

        # 如果未指定 skill_id，尝试自动匹配
        if skill_id is None and config.skill.enable_auto_match:
            SkillRegistry.register_all()
            skill_id = SkillRegistry.match(self.genre)
            if skill_id:
                logger.info(f"自动匹配到预置 Skill: {skill_id}")

        # 匹配失败 → 尝试 LLM 自动生成
        if skill_id is None and config.skill.enable_auto_generate:
            logger.info(f"未找到预置 Skill，尝试 LLM 自动生成（题材: {self.genre}）...")
            generated_id = SkillGenerator.generate(self.genre, self.theme)
            if generated_id:
                skill_id = generated_id
                logger.info(f"LLM 自动生成 Skill 成功: {skill_id}")
            else:
                logger.warning("LLM 自动生成 Skill 失败，将使用默认 Skill")

        # 兜底：使用 fallback
        if skill_id is None:
            skill_id = config.skill.fallback_skill_id
            logger.warning(f"未找到匹配的 Skill，使用默认: {skill_id}")

        # 加载 Skill
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
        同时在后台线程预加载 embedding 模型（与 MySQL 初始化并行）。
        """
        logger.info(f"=== 初始化项目: {self.title} ({self.genre}) ===")

        # 立即启动后台模型预加载（与后续操作并行）
        preload_embedding_model()

        # 初始化数据库
        db_client.init_db()

        # 创建项目（包含 skill_id）
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

        # 初始化子系统（传递 SkillContext）
        self._knowledge_base = KnowledgeBase(project_id)
        self._vector_store = VectorStore(project_id)
        self._outline_generator = OutlineGenerator(project_id, self.genre, self.theme, self.skill_context)
        self._outline_updater = OutlineUpdater(project_id)
        self._chapter_generator = ChapterGenerator(project_id, self.skill_context)
        self._chapter_rewriter = ChapterRewriter(project_id)
        self._character_manager = CharacterManager(project_id)
        self._item_manager = ItemManager(project_id)
        self._world_setting_manager = WorldSettingManager(project_id)
        self._suspense_manager = SuspenseManager(project_id)
        self._quality_evaluator = QualityEvaluator(self.genre)
        self._parameter_optimizer = ParameterOptimizer()
        self._memory_manager = MemoryManager(project_id, self._vector_store)

        logger.info(f"项目初始化完成，ID={project_id}")

    def run(self):
        """
        运行完整的生成流水线

        这是主入口方法，按顺序执行所有阶段。
        """
        logger.info(f"=== 开始生成小说: {self.title} ===")

        try:
            # 阶段1: 知识采集
            collected_knowledge = self._phase_collect_knowledge()

            # 阶段2: 生成世界观
            worldview = self._phase_generate_worldview()

            # 阶段3: 生成初始大纲
            self._phase_generate_initial_outline(collected_knowledge)

            # 阶段4: 主循环 - 生成章节
            self._phase_main_loop(collected_knowledge)

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

        # ---- 1. 加载项目 ----
        project = db_client.get_by_id(Project, project_id)
        if not project:
            raise RuntimeError(f"项目不存在: ID={project_id}")

        self._project = project
        self.title = project.title
        self.genre = project.genre
        self.theme = project.theme or project.genre

        logger.info(f"项目: {project.title} (题材: {project.genre})")

        # 恢复 Skill 上下文
        if project.skill_id:
            try:
                self.skill_context = SkillContext(
                    project.skill_id,
                    project.skill_overrides
                )
                logger.info(f"已恢复 Skill: {project.skill_id}")
            except Exception as e:
                logger.warning(f"Skill 恢复失败: {e}，尝试自动匹配...")
                # 尝试自动匹配
                SkillRegistry.register_all()
                matched = SkillRegistry.match(self.genre)
                if matched:
                    self.skill_context = SkillContext(matched)
                    logger.info(f"自动匹配到 Skill: {matched}")
                else:
                    self.skill_context = SkillContext(config.skill.fallback_skill_id)
                    logger.warning("使用默认 Skill")
        else:
            # 旧项目无 skill_id，尝试自动匹配
            SkillRegistry.register_all()
            matched = SkillRegistry.match(self.genre)
            if matched:
                self.skill_context = SkillContext(matched)
                logger.info(f"自动匹配到 Skill: {matched}")
            else:
                self.skill_context = SkillContext(config.skill.fallback_skill_id)
                logger.info("使用默认 Skill")
        logger.info(f"当前进度: {project.current_chapter}/{project.target_chapters}")

        # ---- 2. 确定续写起始章节 ----
        existing_chapters = db_client.get_all(Chapter, project_id=project_id)
        existing_chapters.sort(key=lambda c: c.chapter_number)

        if not existing_chapters:
            raise RuntimeError(
                f"项目 ID={project_id} 没有已生成的章节，"
                f"请使用 start 命令从头开始生成。"
            )

        last_chapter = existing_chapters[-1].chapter_number

        if from_chapter > 0:
            # 用户指定了起始章节
            if from_chapter > last_chapter + 1:
                raise RuntimeError(
                    f"指定起始章节 {from_chapter} 超出已有范围 "
                    f"(已有到第 {last_chapter} 章)"
                )
            self._current_chapter = from_chapter - 1  # 循环中会 +1
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
                f"无需续写。如需增加章节，请使用 --add-chapters 参数。"
            )
            return

        start_from = self._current_chapter + 1
        remaining = self.target_chapters - self._current_chapter
        logger.info(
            f"将从第 {start_from} 章开始续写，"
            f"还需生成 {remaining} 章 (目标: {self.target_chapters})"
        )

        # ---- 3. 创建输出目录 ----
        output_dir = Path(config.output_dir) / f"{self.title}_{project_id}"
        output_dir.mkdir(parents=True, exist_ok=True)

        # ---- 4. 初始化子系统（传递 SkillContext）----
        self._knowledge_base = KnowledgeBase(project_id)
        self._vector_store = VectorStore(project_id)
        self._outline_generator = OutlineGenerator(project_id, self.genre, self.theme, self.skill_context)
        self._outline_updater = OutlineUpdater(project_id)
        self._chapter_generator = ChapterGenerator(project_id, self.skill_context)
        self._chapter_rewriter = ChapterRewriter(project_id)
        self._character_manager = CharacterManager(project_id)
        self._item_manager = ItemManager(project_id)
        self._world_setting_manager = WorldSettingManager(project_id)
        self._suspense_manager = SuspenseManager(project_id)
        self._quality_evaluator = QualityEvaluator(self.genre)
        self._parameter_optimizer = ParameterOptimizer()
        self._memory_manager = MemoryManager(project_id, self._vector_store)

        # ---- 5. 从 DB 恢复知识上下文 ----
        logger.info("从数据库恢复知识上下文...")
        knowledge = self._restore_knowledge_context()

        # ---- 6. 重建向量存储 ----
        self._rebuild_vector_store(knowledge, existing_chapters)

        # ---- 7. 生成续写大纲 ----
        logger.info("生成续写大纲...")
        knowledge_context = self._build_knowledge_context()
        pending_suspense = self._suspense_manager.get_pending_suspense()
        recent_summaries = self._get_recent_summaries(3)

        self._current_outline = self._outline_updater.update_outline(
            current_chapter=self._current_chapter,
            knowledge_context=knowledge_context,
            pending_suspense=pending_suspense,
            recent_chapters_summary=recent_summaries,
        )

        # ---- 8. 进入主循环 ----
        project.status = "running"
        db_client.update(project)

        logger.info(f"=== 开始续写: {self.title} (从第 {start_from} 章) ===")

        try:
            self._phase_main_loop(knowledge)

            project.status = "completed"
            db_client.update(project)

            logger.info(f"=== 续写完成: {self.title} (当前 {self._current_chapter} 章) ===")

        except Exception as e:
            logger.error(f"续写流水线异常: {e}", exc_info=True)
            project.status = "error"
            db_client.update(project)
            raise

    def _restore_knowledge_context(self) -> Dict[str, str]:
        """
        从数据库恢复已采集的知识

        不重新调用 LLM，直接从 world_settings 表读取之前存储的知识。

        Returns:
            知识字典 {原始类别key: 内容}
        """
        # 原始采集知识的类别映射（反向）
        reverse_map = {
            "world_views": "世界观设定",
            "cultural_knowledge": "传统文化",
            "character_development": "人物塑造",
            "scene_setting": "场景设定",
            "writing_techniques": "写作手法",
            "style_analysis": "风格分析",
            "competitor_analysis": "竞品分析",
        }

        knowledge = {}
        for key, cn_title in reverse_map.items():
            content = self._knowledge_base.get_knowledge_by_category(key)
            if content:
                knowledge[key] = content
                logger.info(f"  恢复知识: {cn_title} ({len(content)} 字)")

        # 也恢复生成的世界观
        generated_keys = [
            "generated_world_setting", "generated_background",
            "generated_power_system", "generated_factions",
        ]
        for gk in generated_keys:
            content = self._knowledge_base.get_knowledge_by_category(gk)
            if content:
                knowledge[gk] = content

        logger.info(f"知识库恢复完成，共 {len(knowledge)} 个类别")
        return knowledge

    def _rebuild_vector_store(
        self,
        knowledge: Dict[str, str],
        existing_chapters: list,
    ):
        """
        重建向量存储

        将已有知识和章节内容重新编码到向量存储中。
        如果向量存储已有数据（同项目），则只补充缺失的部分。

        Args:
            knowledge: 知识字典
            existing_chapters: 已有的章节记录列表
        """
        # 检查向量存储是否已有数据
        if self._vector_store.document_count > 0:
            logger.info(
                f"向量存储已有 {self._vector_store.document_count} 条记录，"
                f"跳过重建"
            )
            return

        docs = []

        # 添加知识文档
        for key, content in knowledge.items():
            if content:
                docs.append({
                    "content": content,
                    "metadata": {"category": key, "type": "knowledge"},
                })

        # 添加已有章节
        for ch in existing_chapters:
            if ch.content:
                docs.append({
                    "content": ch.content,
                    "metadata": {
                        "type": "chapter",
                        "chapter_number": ch.chapter_number,
                        "title": ch.title,
                    },
                })

        if docs:
            self._vector_store.add_documents(docs)
            logger.info(
                f"向量存储重建完成: "
                f"{len(knowledge)} 条知识 + {len(existing_chapters)} 章内容"
            )

    def _phase_collect_knowledge(self) -> Dict[str, str]:
        """阶段1: 知识采集"""
        logger.info("--- 阶段1: 知识采集 ---")
        collector = KnowledgeCollector(self.genre, self.skill_context)
        knowledge = collector.collect_all()
        self._knowledge_base.store_collected_knowledge(knowledge)

        # 将知识加入向量存储
        docs = [
            {"content": v, "metadata": {"category": k}}
            for k, v in knowledge.items()
            if v
        ]
        self._vector_store.add_documents(docs)

        return knowledge

    def _phase_generate_worldview(self) -> Dict[str, str]:
        """阶段2: 生成世界观"""
        logger.info("--- 阶段2: 生成世界观 ---")
        return self._knowledge_base.generate_novel_worldview(self.genre, self.theme)

    def _phase_generate_initial_outline(self, knowledge: Dict[str, str]):
        """阶段3: 生成初始大纲"""
        logger.info("--- 阶段3: 生成初始大纲 ---")
        # 构建知识上下文
        knowledge_context = {
            "世界观设定": self._knowledge_base.get_knowledge_by_category("generated_world_setting"),
            "背景设定": self._knowledge_base.get_knowledge_by_category("generated_background"),
            "力量体系": self._knowledge_base.get_knowledge_by_category("generated_power_system"),
            "势力分布": self._knowledge_base.get_knowledge_by_category("generated_factions"),
            "写作手法": self._knowledge_base.get_knowledge_by_category("writing_techniques"),
        }
        self._current_outline = self._outline_generator.generate_initial_outline(knowledge_context)

    def _phase_main_loop(self, knowledge: Dict[str, str]):
        """阶段4: 主循环 - 逐章生成"""
        logger.info("--- 阶段4: 主循环开始 ---")

        # 获取知识上下文
        knowledge_context = self._build_knowledge_context()

        chapters_data = self._current_outline.get("chapters", [])
        outline_index = 0

        while self._current_chapter < self.target_chapters:
            self._current_chapter += 1
            logger.info(f"\n{'='*50}")
            logger.info(f"正在生成第 {self._current_chapter}/{self.target_chapters} 章")
            logger.info(f"{'='*50}")

            # 获取当前章节大纲
            if outline_index < len(chapters_data):
                chapter_outline = chapters_data[outline_index]
                outline_index += 1
            else:
                # 大纲用完，使用通用大纲
                chapter_outline = {
                    "title": f"第{self._current_chapter}章",
                    "summary": "推进主线剧情",
                    "key_events": [],
                    "characters": [],
                    "suspense": [],
                }

            # 获取悬念状态
            pending_suspense = self._suspense_manager.get_pending_suspense()

            # ===== 构建分层记忆上下文 =====
            layered_context = self._memory_manager.build_full_context(
                current_chapter=self._current_chapter,
                chapter_outline=chapter_outline,
                pending_suspense=pending_suspense,
            )

            # 获取上章结尾（工作记忆的一部分，单独处理以保留 500 字完整度）
            prev_summary = self._get_previous_chapter_summary()
            prev_tail = self._get_previous_chapter_tail()

            if prev_tail:
                prev_summary = f"【上章结尾（本章必须衔接）】\n{prev_tail}\n\n【上章摘要】\n{prev_summary}"

            # 扁平化分层记忆为单一上下文字典
            memory_context = self._memory_manager.flatten_context(layered_context)

            # 合并知识库上下文（静态设定）和记忆上下文
            combined_context = dict(knowledge_context)
            combined_context.update(memory_context)

            # 生成章节内容
            chapter_data = self._chapter_generator.generate_chapter(
                chapter_number=self._current_chapter,
                chapter_outline=chapter_outline,
                knowledge_context=combined_context,
                previous_chapter_summary=prev_summary,
                pending_suspense=pending_suspense,
            )

            # 更新知识库（向量存储）
            self._vector_store.add_documents([{
                "content": chapter_data["content"],
                "metadata": {
                    "type": "chapter",
                    "chapter_number": self._current_chapter,
                    "title": chapter_data["title"],
                },
            }])

            # 更新剧情资产
            self._update_plot_assets(chapter_data)

            # 悬念管理（返回处理结果）
            suspense_result = self._suspense_manager.process_chapter_suspense(
                chapter_number=self._current_chapter,
                chapter_content=chapter_data["content"],
                new_suspense=chapter_data.get("new_suspense", []),
            )

            # ---- 更新 Chapter 记录的资产字段 ----
            new_items_data = chapter_data.get("new_items", [])
            resolved_suspense_ids = suspense_result.get("resolved_suspense_ids", []) if suspense_result else []
            new_suspense_titles = suspense_result.get("new_suspense_titles", []) if suspense_result else []
            
            # 更新 Chapter DB 记录
            chapter_records = db_client.get_all(Chapter, project_id=self.project_id)
            for cr in chapter_records:
                if cr.chapter_number == self._current_chapter:
                    cr.new_items = new_items_data if new_items_data else None
                    cr.new_suspense = new_suspense_titles if new_suspense_titles else cr.new_suspense
                    cr.resolved_suspense = resolved_suspense_ids if resolved_suspense_ids else None
                    db_client.update(cr)
                    break
            
            if new_items_data:
                logger.info(f"第 {self._current_chapter} 章新物品: {[i.get('name','') for i in new_items_data]}")
            if resolved_suspense_ids:
                logger.info(f"第 {self._current_chapter} 章解决悬念: {resolved_suspense_ids}")
            if new_suspense_titles:
                logger.info(f"第 {self._current_chapter} 章新增悬念: {new_suspense_titles[:3]}")

            # ---- 记忆时间线追踪 ----
            self._memory_manager.append_timeline(chapter_data, suspense_result)

            # 质量评估
            quality_score = self._quality_evaluator.evaluate(
                content=chapter_data["content"],
                chapter_number=self._current_chapter,
            )
            logger.info(f"第 {self._current_chapter} 章质量评分: {quality_score:.2f}")

            # ---- 世界设定一致性检查（每5章执行一次） ----
            if self._current_chapter % 5 == 0:
                try:
                    consistency = self._world_setting_manager.verify_consistency(
                        chapter_data["content"]
                    )
                    if not consistency.get("is_consistent", True):
                        issues = consistency.get("issues", [])
                        logger.warning(
                            f"第 {self._current_chapter} 章世界设定不一致: "
                            f"{'; '.join(issues[:3])}"
                        )
                except Exception as e:
                    logger.warning(f"世界设定一致性检查失败: {e}")

            # ---- 低分重写机制 ----
            if self._quality_evaluator.needs_rewrite():
                issues = self._quality_evaluator.diagnose()
                logger.warning(
                    f"第 {self._current_chapter} 章评分 {quality_score:.2f} < "
                    f"{self._quality_evaluator.REWRITE_THRESHOLD}，触发重写"
                )

                rewrite_result = self._chapter_rewriter.rewrite(
                    chapter_number=self._current_chapter,
                    chapter_outline=chapter_outline,
                    original_content=chapter_data["content"],
                    original_score=quality_score,
                    issues=issues,
                    system_prompt=self._chapter_generator.get_system_prompt(),
                    knowledge_context=knowledge_context,
                    previous_chapter_summary=prev_summary,
                )

                if rewrite_result is not None:
                    # 重写成功 → 更新章节数据并重新评估
                    new_content = rewrite_result["content"]

                    # 跑后处理链
                    new_content = self._chapter_generator._apply_post_processing(new_content)

                    # 重新生成摘要
                    new_summary = self._chapter_generator._generate_summary(
                        new_content, self._current_chapter
                    )

                    # 更新章节数据
                    chapter_data["content"] = new_content
                    chapter_data["summary"] = new_summary
                    chapter_data["word_count"] = len(new_content)

                    # 更新数据库记录
                    chapter_records = db_client.get_all(
                        Chapter, project_id=self.project_id
                    )
                    for cr in chapter_records:
                        if cr.chapter_number == self._current_chapter:
                            cr.content = new_content
                            cr.summary = new_summary
                            cr.word_count = len(new_content)
                            db_client.update(cr)
                            break

                    # 重新评估
                    new_score = self._quality_evaluator.evaluate(
                        content=new_content,
                        chapter_number=self._current_chapter,
                    )
                    quality_score = new_score

                    logger.info(
                        f"重写后评分: {new_score:.2f} "
                        f"(原 {rewrite_result['original_score']:.2f}, "
                        f"{'↑' if new_score > rewrite_result['original_score'] else '↓'}"
                        f"{abs(new_score - rewrite_result['original_score']):.2f})"
                    )

                    # 更新重写记录到数据库
                    self._chapter_rewriter.update_chapter_record(
                        chapter_number=self._current_chapter,
                        new_content=new_content,
                        new_score=new_score,
                        rewrite_info={
                            "original_score": rewrite_result["original_score"],
                            "new_score": new_score,
                            "rewrite_reasons": rewrite_result["rewrite_reasons"],
                        },
                    )

                    # 更新向量数据库：删除旧内容，添加新内容
                    self._vector_store.remove_by_chapter(self._current_chapter)
                    self._vector_store.add_documents([{
                        "content": new_content,
                        "metadata": {
                            "type": "chapter",
                            "chapter_number": self._current_chapter,
                            "title": chapter_data["title"],
                        },
                    }])

            # 存储质量评分到章节记录
            chapter_records = db_client.get_all(Chapter, project_id=self.project_id)
            for cr in chapter_records:
                if cr.chapter_number == self._current_chapter:
                    cr.quality_score = quality_score
                    cr.quality_details = self._quality_evaluator.get_last_report()
                    db_client.update(cr)
                    break

            # 动态参数调整
            self._parameter_optimizer.adjust(quality_score)

            # 定期更新大纲
            interval = config.generation.outline_update_interval
            if self._current_chapter % interval == 0:
                logger.info(f"定期更新大纲（每 {interval} 章）...")
                updated_outline = self._outline_updater.update_outline(
                    current_chapter=self._current_chapter,
                    knowledge_context=knowledge_context,
                    pending_suspense=pending_suspense,
                    recent_chapters_summary=self._get_recent_summaries(3),
                )
                chapters_data = updated_outline.get("chapters", [])
                outline_index = 0

                # 更新知识上下文
                knowledge_context = self._build_knowledge_context()

            # 定期记忆维护（每 10 章）
            if self._current_chapter % 10 == 0:
                logger.info("定期记忆维护...")
                self._memory_manager.periodic_maintenance(self._current_chapter)

            # 更新项目进度
            self._project.current_chapter = self._current_chapter
            db_client.update(self._project)

            # 保存章节到文件
            self._save_chapter_to_file(chapter_data)

        logger.info("主循环完成")

        # 输出重写统计
        if self._chapter_rewriter and self._chapter_rewriter.rewrite_history:
            summary = self._chapter_rewriter.get_rewrite_summary()
            logger.info(
                f"重写统计: 共重写 {summary['total_rewrites']} 章, "
                f"平均原始评分 {summary['avg_original_score']:.2f}, "
                f"常见原因: {', '.join(summary['common_reasons'][:3])}"
            )

        # 输出资产统计报告
        try:
            all_chars = self._character_manager.get_active_characters()
            all_items = self._item_manager.get_active_items()
            suspense_report = self._suspense_manager.generate_suspense_report()
            
            logger.info(
                f"资产统计: {len(all_chars)} 个活跃角色, "
                f"{len(all_items)} 个活跃物品"
            )
            logger.info(suspense_report)
            
            # 物品盘点报告
            inventory = self._item_manager.inventory_check(self._current_chapter)
            if inventory.get("suggestions"):
                logger.warning(f"物品盘点建议: {'; '.join(inventory['suggestions'][:3])}")
        except Exception as e:
            logger.warning(f"资产统计报告生成失败: {e}")

        # 输出记忆系统统计
        try:
            from novel_agent.database.models import MemoryArchive
            archives = db_client.get_all(MemoryArchive, project_id=self.project_id)
            vol_summaries = [a for a in archives if a.archive_type == "volume_summary"]
            char_arcs = [a for a in archives if a.archive_type == "character_arc"]
            susp_archives = [a for a in archives if a.archive_type == "suspense_archive"]
            
            vector_count = self._vector_store.document_count if self._vector_store else 0
            
            logger.info(
                f"记忆系统统计: "
                f"{len(vol_summaries)} 条卷摘要, "
                f"{len(char_arcs)} 条角色弧线, "
                f"{len(susp_archives)} 条悬念归档, "
                f"{vector_count} 条向量切片, "
                f"时间线 {len(self._memory_manager._timeline)} 条"
            )
        except Exception as e:
            logger.warning(f"记忆统计失败: {e}")

    def _build_knowledge_context(self) -> Dict[str, str]:
        """构建当前知识上下文"""
        return {
            "世界观设定": self._knowledge_base.get_knowledge_by_category("generated_world_setting"),
            "背景设定": self._knowledge_base.get_knowledge_by_category("generated_background"),
            "力量体系": self._knowledge_base.get_knowledge_by_category("generated_power_system"),
            "势力分布": self._knowledge_base.get_knowledge_by_category("generated_factions"),
            "写作手法": self._knowledge_base.get_knowledge_by_category("writing_techniques"),
            "风格参考": self._knowledge_base.get_knowledge_by_category("style_analysis"),
        }

    def _get_previous_chapter_summary(self) -> str:
        """获取上一章摘要"""
        if self._current_chapter <= 1:
            return ""
        records = db_client.get_all(Chapter, project_id=self.project_id)
        for r in records:
            if r.chapter_number == self._current_chapter - 1:
                return r.summary or ""
        return ""

    def _get_previous_chapter_tail(self) -> str:
        """
        获取上一章的最后500字

        用于确保本章开头能自然衔接上章结尾的悬念/场景。
        """
        if self._current_chapter <= 1:
            return ""
        records = db_client.get_all(Chapter, project_id=self.project_id)
        for r in records:
            if r.chapter_number == self._current_chapter - 1:
                content = r.content or ""
                if len(content) > 500:
                    return content[-500:]
                return content
        return ""

    def _get_recent_summaries(self, count: int) -> str:
        """获取最近 N 章的摘要"""
        records = db_client.get_all(Chapter, project_id=self.project_id)
        recent = sorted(records, key=lambda r: r.chapter_number, reverse=True)[:count]
        recent.reverse()
        summaries = [
            f"第{r.chapter_number}章「{r.title}」: {(r.summary or '')[:200]}"
            for r in recent
        ]
        return "\n".join(summaries)

    def _build_asset_context(self) -> Dict[str, str]:
        """
        构建当前资产上下文，用于注入章节生成的 LLM 上下文
        
        包含：活跃角色档案、活跃物品状态、世界观设定、活跃悬念
        
        Returns:
            资产上下文字典 {key: text}
        """
        asset_context = {}
        
        # 1. 活跃角色档案
        try:
            char_context = self._character_manager.get_active_character_context(limit=6)
            if char_context:
                asset_context["角色档案"] = char_context
        except Exception as e:
            logger.warning(f"获取角色上下文失败: {e}")
        
        # 2. 活跃物品状态
        try:
            item_context = self._item_manager.get_active_item_context(limit=8)
            if item_context:
                asset_context["物品功法"] = item_context
        except Exception as e:
            logger.warning(f"获取物品上下文失败: {e}")
        
        # 3. 世界观设定摘要
        try:
            world_context = self._world_setting_manager.get_brief_world_context()
            if world_context:
                asset_context["世界设定"] = world_context[:800]
        except Exception as e:
            logger.warning(f"获取世界设定上下文失败: {e}")
        
        # 4. 活跃悬念状态报告
        try:
            suspense_report = self._suspense_manager.generate_suspense_report()
            if suspense_report and "无活跃悬念" not in suspense_report:
                asset_context["悬念状态"] = suspense_report[:600]
        except Exception as e:
            logger.warning(f"获取悬念上下文失败: {e}")
        
        return asset_context

    def _update_plot_assets(self, chapter_data: Dict):
        """
        更新剧情资产（角色、物品、剧情节点）
        
        增强版：
        1. 确保新角色存在档案
        2. LLM 批量提取角色更新信息
        3. LLM 提取新物品
        4. 创建剧情节点记录
        5. 定期物品盘点
        """
        chapter_number = chapter_data["chapter_number"]
        content = chapter_data["content"]
        
        # ---- 1. 确保新角色存在档案 ----
        new_chars = chapter_data.get("new_characters", [])
        for char_name in new_chars:
            self._character_manager.ensure_character(
                name=char_name,
                chapter_number=chapter_number,
            )
        
        # ---- 2. LLM 批量提取角色信息更新 ----
        # 获取当前所有活跃角色名，从中筛选本章出场的
        try:
            active_chars = self._character_manager.get_active_characters()
            active_char_names = [c.name for c in active_chars]
            
            # 通过简单文本匹配判断哪些角色在本章出场
            chars_in_chapter = [
                name for name in active_char_names
                if name in content
            ]
            
            # 也加入 new_characters（可能还没在 DB 里有档案）
            for name in new_chars:
                if name not in chars_in_chapter:
                    chars_in_chapter.append(name)
            
            if chars_in_chapter:
                self._character_manager.batch_update_from_chapter(
                    character_names=chars_in_chapter,
                    chapter_content=content,
                    chapter_number=chapter_number,
                )
        except Exception as e:
            logger.warning(f"角色批量更新失败: {e}")
        
        # ---- 3. LLM 提取新物品 ----
        new_items = []
        try:
            extracted_items = self._item_manager.extract_items_from_chapter(
                chapter_content=content,
                chapter_number=chapter_number,
            )
            if extracted_items:
                new_items = [
                    {"name": item.get("name", ""), "type": item.get("item_type", "")}
                    for item in extracted_items
                ]
                logger.info(f"本章提取到 {len(new_items)} 个新物品")
        except Exception as e:
            logger.warning(f"物品提取失败: {e}")
        
        # ---- 4. 创建剧情节点记录 ----
        try:
            key_events = chapter_data.get("key_events", [])
            title = chapter_data.get("title", f"第{chapter_number}章")
            
            if key_events:
                # 为每个关键事件创建 PlotPoint
                for event in key_events[:2]:  # 最多2个
                    plot_point = PlotPoint(
                        project_id=self.project_id,
                        chapter_number=chapter_number,
                        plot_type="event",
                        title=f"{title}: {str(event)[:30]}",
                        description=str(event)[:200],
                        characters_involved=new_chars[:5],
                    )
                    db_client.add(plot_point)
            else:
                # 没有明确的关键事件，用摘要创建一个总体节点
                summary = chapter_data.get("summary", "")
                if summary:
                    plot_point = PlotPoint(
                        project_id=self.project_id,
                        chapter_number=chapter_number,
                        plot_type="chapter_summary",
                        title=title,
                        description=summary[:300],
                        characters_involved=new_chars[:5],
                    )
                    db_client.add(plot_point)
        except Exception as e:
            logger.warning(f"剧情节点创建失败: {e}")
        
        # ---- 5. 定期物品盘点（每10章） ----
        if chapter_number % 10 == 0:
            try:
                self._item_manager.prevent_inflation(chapter_number)
            except Exception as e:
                logger.warning(f"物品盘点失败: {e}")
        
        # 将提取结果存回 chapter_data 以便后续写入 DB
        chapter_data["new_items"] = new_items

    def _save_chapter_to_file(self, chapter_data: Dict):
        """将章节保存到文件"""
        import re
        output_dir = Path(config.output_dir) / f"{self.title}_{self.project_id}" / "chapters"
        output_dir.mkdir(parents=True, exist_ok=True)

        # 清理文件名中 Windows 不允许的字符: \ / : * ? " < > |
        safe_title = re.sub(r'[\\/:*?"<>|]', '', chapter_data['title'])
        filename = f"第{chapter_data['chapter_number']:03d}章_{safe_title}.txt"
        filepath = output_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"第{chapter_data['chapter_number']}章 {chapter_data['title']}\n\n")
            f.write(chapter_data["content"])

        logger.info(f"章节已保存: {filepath}")
