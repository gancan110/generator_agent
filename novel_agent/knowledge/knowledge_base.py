"""
知识库管理器

管理小说创作过程中的所有结构化知识，
包括知识的存储、检索、更新和生命周期管理。
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from novel_agent.database.mysql_client import db_client
from novel_agent.database.models import WorldSetting, Project
from novel_agent.utils.llm_client import llm_client

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """
    知识库管理器

    负责：
    - 将采集的知识结构化存储到 MySQL
    - 基于已有知识生成小说专属世界观
    - 知识的检索和更新
    """

    def __init__(self, project_id: int):
        """
        Args:
            project_id: 关联的项目 ID
        """
        self.project_id = project_id

    def store_knowledge(self, category: str, title: str, content: str, metadata: dict = None):
        """
        存储知识到数据库

        Args:
            category: 知识类别（world_view/culture/character/scene/technique/style/competitor）
            title: 知识标题
            content: 知识内容
            metadata: 额外元数据
        """
        setting = WorldSetting(
            project_id=self.project_id,
            category=category,
            title=title,
            content=content,
            metadata_json=metadata or {},
        )
        db_client.add(setting)
        logger.info(f"知识已存储: [{category}] {title}")

    def store_collected_knowledge(self, knowledge_dict: Dict[str, str]):
        """
        批量存储采集到的知识

        Args:
            knowledge_dict: 知识字典 {类别: 内容}
        """
        category_map = {
            "world_views": "世界观设定",
            "cultural_knowledge": "传统文化",
            "character_development": "人物塑造",
            "scene_setting": "场景设定",
            "writing_techniques": "写作手法",
            "style_analysis": "风格分析",
            "competitor_analysis": "竞品分析",
        }

        for key, content in knowledge_dict.items():
            if content:
                title = category_map.get(key, key)
                self.store_knowledge(
                    category=key,
                    title=f"{title} - 采集知识",
                    content=content,
                )

        logger.info(f"已存储 {len(knowledge_dict)} 条采集知识")

    def generate_novel_worldview(self, genre: str, theme: str) -> Dict[str, str]:
        """
        基于采集知识，生成小说专属世界观

        Args:
            genre: 小说题材
            theme: 小说主题

        Returns:
            世界观字典 {类别: 内容}
        """
        logger.info(f"正在生成小说世界观: {genre} - {theme}")

        # 获取已有知识作为参考
        existing_knowledge = self.get_knowledge_by_category("world_views")
        culture_knowledge = self.get_knowledge_by_category("cultural_knowledge")

        context = {
            "参考世界观": existing_knowledge[:2000] if existing_knowledge else "无",
            "文化知识": culture_knowledge[:2000] if culture_knowledge else "无",
        }

        # 生成世界观各维度
        worldview_components = {}

        # 1. 世界观设定
        worldview_components["world_setting"] = llm_client.generate_structured(
            prompt=(
                f"基于参考信息，为一部 [{genre}] 类型、主题为 [{theme}] 的小说，"
                f"设计一套完整的世界观设定。\n"
                f"要求包含：世界起源、世界结构、时间体系、基本法则。"
            ),
            context=context,
            max_tokens=3000,
        )

        # 2. 背景设定
        worldview_components["background"] = llm_client.generate_structured(
            prompt=(
                f"基于已有世界观，为这部小说设计详细的背景设定。\n"
                f"要求包含：时代背景、社会制度、文明程度、主要矛盾。"
            ),
            context={**context, "世界观": worldview_components["world_setting"][:1500]},
            max_tokens=3000,
        )

        # 3. 力量体系与规则
        worldview_components["power_system"] = llm_client.generate_structured(
            prompt=(
                f"为这部小说设计一套完整的力量体系和世界规则。\n"
                f"要求包含：修炼境界（从低到高，至少8个等级）、"
                f"突破条件、天道规则、特殊限制。"
            ),
            context={**context, "世界观": worldview_components["world_setting"][:1500]},
            max_tokens=3000,
        )

        # 4. 势力分布
        worldview_components["factions"] = llm_client.generate_structured(
            prompt=(
                f"为这部小说设计势力分布图。\n"
                f"要求包含：主要势力（至少5个）、势力关系（盟友/敌对/中立）、"
                f"势力等级、各势力核心人物简介。"
            ),
            context={
                **context,
                "世界观": worldview_components["world_setting"][:1000],
                "背景": worldview_components["background"][:1000],
            },
            max_tokens=3000,
        )

        # 存储生成的世界观
        for key, content in worldview_components.items():
            self.store_knowledge(
                category=f"generated_{key}",
                title=f"生成 - {key}",
                content=content,
                metadata={"genre": genre, "theme": theme},
            )

        logger.info("小说世界观生成完成")
        return worldview_components

    def get_knowledge_by_category(self, category: str) -> str:
        """
        获取指定类别的知识内容（合并多条记录）

        Args:
            category: 知识类别

        Returns:
            合并后的知识文本
        """
        records = db_client.get_all(WorldSetting, project_id=self.project_id, category=category)
        if not records:
            return ""
        return "\n\n---\n\n".join(r.content for r in records)

    def get_all_knowledge(self) -> Dict[str, str]:
        """获取项目的所有知识"""
        records = db_client.get_all(WorldSetting, project_id=self.project_id)
        knowledge = {}
        for record in records:
            key = f"{record.category}_{record.id}"
            knowledge[key] = record.content
        return knowledge

    def search_knowledge(self, query: str, top_k: int = 5) -> List[dict]:
        """
        在知识库中搜索相关知识

        Args:
            query: 搜索查询
            top_k: 返回结果数量

        Returns:
            相关知识列表
        """
        # 简单关键词匹配（后续可升级为向量检索）
        all_knowledge = self.get_all_knowledge()
        results = []
        for key, content in all_knowledge.items():
            # 简单的关键词相关性评分
            keywords = query.split()
            score = sum(1 for kw in keywords if kw in content)
            if score > 0:
                results.append({"key": key, "content": content, "score": score})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
