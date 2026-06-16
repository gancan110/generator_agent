"""
知识采集器单元测试
"""

import pytest
from unittest.mock import MagicMock, patch

from novel_agent.knowledge.collector import KnowledgeCollector


class TestKnowledgeCollector:
    """KnowledgeCollector类测试"""

    @patch("novel_agent.knowledge.collector.llm_client")
    def test_init(self, mock_llm):
        """测试初始化"""
        collector = KnowledgeCollector("玄幻修仙")
        assert collector.genre == "玄幻修仙"
        assert collector.skill is None
        assert collector.collected_knowledge == {}

    @patch("novel_agent.knowledge.collector.llm_client")
    def test_init_with_skill(self, mock_llm):
        """测试带Skill初始化"""
        mock_skill = MagicMock()
        collector = KnowledgeCollector("都市重生", skill_context=mock_skill)
        assert collector.skill == mock_skill

    @patch("novel_agent.knowledge.collector.llm_client")
    def test_collect_all(self, mock_llm):
        """测试采集所有知识"""
        mock_llm.generate.return_value = "测试知识内容"

        collector = KnowledgeCollector("玄幻修仙")
        result = collector.collect_all()

        assert isinstance(result, dict)
        assert "world_views" in result
        assert "cultural_knowledge" in result
        assert "character_development" in result
        assert len(result) == 7

    @patch("novel_agent.knowledge.collector.llm_client")
    def test_collect_world_views(self, mock_llm):
        """测试采集世界观"""
        mock_llm.generate.return_value = "修仙世界观设定"

        collector = KnowledgeCollector("玄幻修仙")
        result = collector._collect_world_views()

        assert result == "修仙世界观设定"
        mock_llm.generate.assert_called_once()

    @patch("novel_agent.knowledge.collector.llm_client")
    def test_collect_cultural_knowledge(self, mock_llm):
        """测试采集文化知识"""
        mock_llm.generate.return_value = "传统文化知识"

        collector = KnowledgeCollector("玄幻修仙")
        result = collector._collect_cultural_knowledge()

        assert result == "传统文化知识"

    @patch("novel_agent.knowledge.collector.llm_client")
    def test_collect_with_skill_prompt(self, mock_llm):
        """测试使用Skill定制prompt采集"""
        mock_skill = MagicMock()
        mock_skill.get_cultural_knowledge_prompt.return_value = "定制prompt"
        mock_llm.generate.return_value = "定制知识"

        collector = KnowledgeCollector("玄幻修仙", skill_context=mock_skill)
        result = collector._collect_cultural_knowledge()

        assert result == "定制知识"
        mock_skill.get_cultural_knowledge_prompt.assert_called_once()

    @patch("novel_agent.knowledge.collector.llm_client")
    def test_collect_error_handling(self, mock_llm):
        """测试采集错误处理"""
        mock_llm.generate.side_effect = Exception("API错误")

        collector = KnowledgeCollector("玄幻修仙")
        result = collector.collect_all()

        # 应该返回空字符串而不是抛出异常
        assert all(v == "" for v in result.values())

    @patch("novel_agent.knowledge.collector.llm_client")
    def test_collect_character_development(self, mock_llm):
        """测试采集人物塑造"""
        mock_llm.generate.return_value = "人物塑造技巧"

        collector = KnowledgeCollector("都市重生")
        result = collector._collect_character_development()

        assert result == "人物塑造技巧"

    @patch("novel_agent.knowledge.collector.llm_client")
    def test_collect_writing_techniques(self, mock_llm):
        """测试采集写作手法"""
        mock_llm.generate.return_value = "写作手法分析"

        collector = KnowledgeCollector("科幻星际")
        result = collector._collect_writing_techniques()

        assert result == "写作手法分析"


class TestKnowledgeCollectorIntegration:
    """知识采集器集成测试"""

    @patch("novel_agent.knowledge.collector.llm_client")
    def test_multiple_genres(self, mock_llm):
        """测试多题材采集"""
        mock_llm.generate.return_value = "知识内容"

        genres = ["玄幻修仙", "都市重生", "科幻星际", "规则怪谈"]
        for genre in genres:
            collector = KnowledgeCollector(genre)
            result = collector.collect_all()
            assert len(result) == 7
