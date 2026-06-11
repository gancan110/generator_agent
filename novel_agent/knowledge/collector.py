"""
多源知识采集器

通过 LLM 和网络搜索采集小说创作所需的知识，
包括世界观设定、传统文化、人物塑造技巧、竞品分析等。
"""

import logging
from typing import Dict, List, Optional, TYPE_CHECKING

from novel_agent.utils.llm_client import llm_client

if TYPE_CHECKING:
    from novel_agent.skills.context import SkillContext

logger = logging.getLogger(__name__)


class KnowledgeCollector:
    """
    多源知识采集器

    从多个维度采集小说创作知识：
    - 世界观设定（主流小说的世界构建方式）
    - 传统文化底蕴（根据题材定制）
    - 人物塑造方法
    - 场景设定技巧
    - 写作手法分析
    - 风格分析（根据题材定制参考作家）
    - 竞品分析
    """

    def __init__(self, genre: str, skill_context: Optional["SkillContext"] = None):
        """
        Args:
            genre: 小说题材类型（如"玄幻修仙"、"都市重生"）
            skill_context: Skill 上下文（可选）
        """
        self.genre = genre
        self.skill = skill_context
        self.collected_knowledge: Dict[str, str] = {}

    def collect_all(self) -> Dict[str, str]:
        """
        采集所有维度的知识

        Returns:
            知识字典，key 为知识类别，value 为知识内容
        """
        logger.info(f"开始采集 [{self.genre}] 类型的创作知识...")

        collectors = [
            ("world_views", self._collect_world_views),
            ("cultural_knowledge", self._collect_cultural_knowledge),
            ("character_development", self._collect_character_development),
            ("scene_setting", self._collect_scene_setting),
            ("writing_techniques", self._collect_writing_techniques),
            ("style_analysis", self._collect_style_analysis),
            ("competitor_analysis", self._collect_competitor_analysis),
        ]

        for key, collector_func in collectors:
            try:
                logger.info(f"  采集中: {key}...")
                result = collector_func()
                self.collected_knowledge[key] = result
                logger.info(f"  完成: {key} ({len(result)} 字符)")
            except Exception as e:
                logger.error(f"  采集失败: {key} - {e}")
                self.collected_knowledge[key] = ""

        logger.info("知识采集完成")
        return self.collected_knowledge

    def _collect_world_views(self) -> str:
        """采集主流世界观设定"""
        return llm_client.generate(
            prompt=(
                f"请详细分析 {self.genre} 类型小说中主流的世界观设定方式。"
                f"包括但不限于：世界架构、力量体系、修炼境界、社会制度等。"
                f"请提供具体的设定参考和创作建议。"
            ),
            system_prompt="你是一位资深的网文编辑和世界观设计师。",
            temperature=0.5,
            max_tokens=4096,
        )

    def _collect_cultural_knowledge(self) -> str:
        """采集文化/背景知识（根据 Skill 定制）"""
        # 检查 Skill 是否有定制 prompt
        if self.skill:
            skill_prompt = self.skill.get_cultural_knowledge_prompt()
            if skill_prompt:
                logger.info("  使用 Skill 定制的文化知识采集 prompt")
                return llm_client.generate(
                    prompt=skill_prompt,
                    system_prompt="你是一位专业的文化知识顾问，擅长将文化知识与小说创作结合。",
                    temperature=0.3,
                    max_tokens=4096,
                )

        # 默认 prompt（通用版本）
        return llm_client.generate(
            prompt=(
                f"请系统整理以下与 {self.genre} 小说创作相关的文化背景知识：\n"
                "1. 该题材的核心文化元素和传统\n"
                "2. 相关的历史、传说或设定体系\n"
                "3. 社会结构和权力关系\n"
                "4. 特色术语和称谓\n"
                "5. 常见的场景和道具\n"
                "6. 该题材读者的期待和偏好\n"
                "请简明扼要地整理，突出可用于小说创作的元素。"
            ),
            system_prompt="你是一位专业的文化知识顾问。",
            temperature=0.3,
            max_tokens=4096,
        )

    def _collect_character_development(self) -> str:
        """采集人物塑造方法"""
        return llm_client.generate(
            prompt=(
                f"请详细分析 {self.genre} 类型小说中的人物塑造技巧：\n"
                "1. 主角设计：如何设计有吸引力的主角（性格、动机、成长弧线）\n"
                "2. 配角设计：如何设计功能性配角\n"
                "3. 反派设计：如何设计有深度的反派\n"
                "4. 人物关系：如何构建复杂的人物关系网\n"
                "5. 对话设计：如何通过对话展现人物性格\n"
                "请提供具体的方法论和示例。"
            ),
            system_prompt="你是一位专业的小说人物设计大师。",
            temperature=0.5,
            max_tokens=4096,
        )

    def _collect_scene_setting(self) -> str:
        """采集场景设定技巧"""
        return llm_client.generate(
            prompt=(
                f"请分析 {self.genre} 类型小说中的场景设定方法：\n"
                "1. 地理环境设计（地图层级、区域特色）\n"
                "2. 势力分布设计（门派、家族、帝国）\n"
                "3. 特殊场景设计（秘境、副本、战场）\n"
                "4. 日常场景设计（修炼、交易、社交）\n"
                "请提供具体的设计模式和创作建议。"
            ),
            system_prompt="你是一位专业的小说场景设计师。",
            temperature=0.5,
            max_tokens=4096,
        )

    def _collect_writing_techniques(self) -> str:
        """采集写作手法"""
        return llm_client.generate(
            prompt=(
                f"请系统分析 {self.genre} 类型小说的写作手法：\n"
                "1. 叙事结构（线性叙事、多线并行、倒叙插叙）\n"
                "2. 节奏控制（张弛有度、高潮铺垫）\n"
                "3. 爽点设置（打脸、升级、获得宝物）\n"
                "4. 悬念设置（伏笔、悬念、反转）\n"
                "5. 黄金三章（开头如何留住读者）\n"
                "6. 商业化写作套路（期待感设置、爽点节奏）\n"
                "请结合具体的商业写作经验提供建议。"
            ),
            system_prompt="你是一位畅销网文作家兼写作教练。",
            temperature=0.5,
            max_tokens=4096,
        )

    def _collect_style_analysis(self) -> str:
        """分析知名作者风格（根据 Skill 定制参考作家）"""
        # 检查 Skill 是否有定制的作者列表
        if self.skill:
            authors = self.skill.get_style_analysis_authors()
            if authors:
                logger.info(f"  使用 Skill 定制的参考作家: {[a['name'] for a in authors]}")
                author_lines = [
                    f"{i+1}. {a['name']}：分析其{a['focus']}"
                    for i, a in enumerate(authors)
                ]
                prompt = (
                    "请分析以下知名网文作者的写作风格特点：\n"
                    + "\n".join(author_lines)
                    + "\n\n请总结可借鉴的写作技巧，用于指导AI小说生成。"
                )
                return llm_client.generate(
                    prompt=prompt,
                    system_prompt="你是一位专业的文学评论家和网文研究者。",
                    temperature=0.3,
                    max_tokens=4096,
                )

        # 默认 prompt（通用版本，不硬编码特定作者）
        return llm_client.generate(
            prompt=(
                f"请推荐并分析 3 位 {self.genre} 类型小说的代表性作家：\n"
                "对每位作家，分析其：\n"
                "- 叙事风格和节奏特点\n"
                "- 人物塑造手法\n"
                "- 世界观构建方式\n"
                "- 独特的写作技巧\n"
                "请总结可借鉴的写作技巧，用于指导AI小说生成。"
            ),
            system_prompt="你是一位专业的文学评论家和网文研究者。",
            temperature=0.3,
            max_tokens=4096,
        )

    def _collect_competitor_analysis(self) -> str:
        """竞品分析"""
        return llm_client.generate(
            prompt=(
                f"请对 {self.genre} 类型小说进行竞品分析：\n"
                "1. 头部作品分析：列举3-5部代表性作品，分析其成功要素\n"
                "2. 黄金三章拆解：这些作品的开头如何吸引读者\n"
                "3. 期待感设置：如何让读者持续追读\n"
                "4. 爽点节奏：高潮和低谷如何安排\n"
                "5. 常见雷区：该类型小说容易犯的错误\n"
                "请提供具体的商业写作经验和数据支撑。"
            ),
            system_prompt="你是一位资深的网文市场分析师。",
            temperature=0.3,
            max_tokens=4096,
        )
