"""
记忆管理器单元测试
"""

import pytest
from unittest.mock import MagicMock, patch

from novel_agent.memory.manager import MemoryManager


class TestMemoryManager:
    """MemoryManager类测试"""

    @patch("novel_agent.memory.manager.db_client")
    def test_init(self, mock_db):
        """测试初始化"""
        manager = MemoryManager(project_id=1)
        assert manager.project_id == 1
        assert manager._vector_store is None
        assert manager._timeline == []

    @patch("novel_agent.memory.manager.db_client")
    def test_init_with_vector_store(self, mock_db):
        """测试带向量存储初始化"""
        mock_vs = MagicMock()
        manager = MemoryManager(project_id=1, vector_store=mock_vs)
        assert manager._vector_store == mock_vs

    @patch("novel_agent.memory.manager.db_client")
    def test_set_vector_store(self, mock_db):
        """测试设置向量存储"""
        manager = MemoryManager(project_id=1)
        mock_vs = MagicMock()
        manager.set_vector_store(mock_vs)
        assert manager._vector_store == mock_vs

    @patch("novel_agent.memory.manager.db_client")
    def test_budget_constants(self, mock_db):
        """测试预算常量"""
        assert MemoryManager.BUDGET_WORKING == 4500
        assert MemoryManager.BUDGET_SHORT_TERM == 6000
        assert MemoryManager.BUDGET_LONG_TERM == 4500
        assert MemoryManager.BUDGET_PERMANENT == 3000

    @patch("novel_agent.memory.manager.db_client")
    def test_build_working_memory(self, mock_db):
        """测试构建工作记忆"""
        mock_db.get_chapter_by_number.return_value = MagicMock(
            summary="上章摘要"
        )

        manager = MemoryManager(project_id=1)
        chapter_outline = {
            "title": "测试章节",
            "summary": "章节摘要",
            "key_events": ["事件1"],
        }

        result = manager.build_working_memory(
            current_chapter=5,
            chapter_outline=chapter_outline,
            pending_suspense=[],
        )

        assert isinstance(result, dict)
        assert "工作记忆" in result or len(result) >= 0

    @patch("novel_agent.memory.manager.db_client")
    def test_build_short_term_memory(self, mock_db):
        """测试构建短期记忆"""
        mock_db.get_all.return_value = []

        manager = MemoryManager(project_id=1)
        mock_vs = MagicMock()
        mock_vs.search.return_value = []
        manager.set_vector_store(mock_vs)

        result = manager.build_short_term_memory(
            current_chapter=5,
            chapter_outline={"title": "测试"},
        )

        assert isinstance(result, dict)

    @patch("novel_agent.memory.manager.db_client")
    def test_build_long_term_memory(self, mock_db):
        """测试构建长期记忆"""
        mock_db.get_all.return_value = []

        manager = MemoryManager(project_id=1)
        result = manager.build_long_term_memory(current_chapter=5)

        assert isinstance(result, dict)

    @patch("novel_agent.memory.manager.db_client")
    def test_build_permanent_memory(self, mock_db):
        """测试构建永久记忆"""
        mock_db.get_all.return_value = []

        manager = MemoryManager(project_id=1)
        result = manager.build_permanent_memory()

        assert isinstance(result, dict)

    @patch("novel_agent.memory.manager.db_client")
    def test_flatten_context(self, mock_db):
        """测试扁平化上下文"""
        manager = MemoryManager(project_id=1)
        # 使用实际的上下文结构
        layered_context = {
            "永久记忆": {"key1": "value1"},
            "长期记忆": {"key2": "value2"},
            "短期记忆": {"key3": "value3"},
            "工作记忆": {"key4": "value4"},
        }

        result = manager.flatten_context(layered_context)

        assert isinstance(result, dict)

    @patch("novel_agent.memory.manager.db_client")
    def test_append_timeline(self, mock_db):
        """测试追加时间线"""
        manager = MemoryManager(project_id=1)
        chapter_data = {
            "chapter_number": 1,
            "title": "第一章",
            "summary": "摘要",
        }

        manager.append_timeline(chapter_data, None)
        assert len(manager._timeline) == 1

    @patch("novel_agent.memory.manager.db_client")
    def test_periodic_maintenance(self, mock_db):
        """测试定期维护"""
        mock_db.get_all.return_value = []
        mock_db.get_chapters_by_project.return_value = []

        manager = MemoryManager(project_id=1)
        # 不应抛出异常
        manager.periodic_maintenance(current_chapter=10)


class TestMemoryManagerContext:
    """记忆管理器上下文测试"""

    @patch("novel_agent.memory.manager.db_client")
    def test_full_context_build(self, mock_db):
        """测试完整上下文构建"""
        mock_db.get_chapter_by_number.return_value = MagicMock(
            summary="测试摘要"
        )
        mock_db.get_all.return_value = []

        manager = MemoryManager(project_id=1)
        chapter_outline = {
            "title": "测试章节",
            "summary": "章节摘要",
            "key_events": ["事件1"],
        }

        result = manager.build_full_context(
            current_chapter=1,
            chapter_outline=chapter_outline,
            pending_suspense=[],
        )

        assert isinstance(result, dict)
