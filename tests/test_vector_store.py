"""
向量存储模块单元测试
"""

import json
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

from novel_agent.knowledge.vector_store import VectorStore


class TestVectorStore:
    """VectorStore类测试"""

    @patch("novel_agent.knowledge.vector_store.get_embedding_model")
    @patch("novel_agent.knowledge.vector_store.config")
    def test_init_creates_directory(self, mock_config, mock_get_model, tmp_path):
        """测试初始化时创建目录"""
        mock_config.vector_db.db_path = str(tmp_path)
        mock_config.vector_db.chunk_size = 2000
        mock_config.vector_db.chunk_overlap = 200
        mock_get_model.return_value = None

        project_id = 1
        vs = VectorStore(project_id)

        expected_dir = tmp_path / f"project_{project_id}"
        assert expected_dir.exists()
        assert vs.project_id == project_id

    @patch("novel_agent.knowledge.vector_store.get_embedding_model")
    @patch("novel_agent.knowledge.vector_store.config")
    def test_add_documents_empty(self, mock_config, mock_get_model, tmp_path):
        """测试添加空文档列表"""
        mock_config.vector_db.db_path = str(tmp_path)
        mock_config.vector_db.chunk_size = 2000
        mock_config.vector_db.chunk_overlap = 200
        mock_get_model.return_value = None

        vs = VectorStore(1)
        vs.add_documents([])

        assert vs.document_count == 0

    @patch("novel_agent.knowledge.vector_store.get_embedding_model")
    @patch("novel_agent.knowledge.vector_store.config")
    def test_add_documents_with_content(self, mock_config, mock_get_model, tmp_path):
        """测试添加包含内容的文档"""
        mock_config.vector_db.db_path = str(tmp_path)
        mock_config.vector_db.chunk_size = 2000
        mock_config.vector_db.chunk_overlap = 200

        # 模拟embedding模型
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1, 384)
        mock_get_model.return_value = mock_model

        vs = VectorStore(1)
        documents = [
            {"content": "测试文档内容", "metadata": {"type": "test"}}
        ]
        vs.add_documents(documents)

        assert vs.document_count == 1

    @patch("novel_agent.knowledge.vector_store.get_embedding_model")
    @patch("novel_agent.knowledge.vector_store.config")
    def test_search_empty_store(self, mock_config, mock_get_model, tmp_path):
        """测试在空存储中搜索"""
        mock_config.vector_db.db_path = str(tmp_path)
        mock_config.vector_db.chunk_size = 2000
        mock_config.vector_db.chunk_overlap = 200
        mock_get_model.return_value = None

        vs = VectorStore(1)
        results = vs.search("测试查询")

        assert results == []

    @patch("novel_agent.knowledge.vector_store.get_embedding_model")
    @patch("novel_agent.knowledge.vector_store.config")
    def test_clear(self, mock_config, mock_get_model, tmp_path):
        """测试清空存储"""
        mock_config.vector_db.db_path = str(tmp_path)
        mock_config.vector_db.chunk_size = 2000
        mock_config.vector_db.chunk_overlap = 200

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1, 384)
        mock_get_model.return_value = mock_model

        vs = VectorStore(1)
        vs.add_documents([{"content": "测试内容"}])
        assert vs.document_count == 1

        vs.clear()
        assert vs.document_count == 0

    @patch("novel_agent.knowledge.vector_store.get_embedding_model")
    @patch("novel_agent.knowledge.vector_store.config")
    def test_remove_by_chapter(self, mock_config, mock_get_model, tmp_path):
        """测试按章节删除"""
        mock_config.vector_db.db_path = str(tmp_path)
        mock_config.vector_db.chunk_size = 2000
        mock_config.vector_db.chunk_overlap = 200

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1, 384)
        mock_get_model.return_value = mock_model

        vs = VectorStore(1)
        vs.add_documents([
            {"content": "第1章内容", "metadata": {"type": "chapter", "chapter_number": 1}},
            {"content": "第2章内容", "metadata": {"type": "chapter", "chapter_number": 2}},
        ])
        # 文档会被切片，所以实际数量可能大于2
        initial_count = vs.document_count
        assert initial_count >= 2

        removed = vs.remove_by_chapter(1)
        assert removed >= 1
        assert vs.document_count < initial_count

    @patch("novel_agent.knowledge.vector_store.get_embedding_model")
    @patch("novel_agent.knowledge.vector_store.config")
    def test_save_and_load_index(self, mock_config, mock_get_model, tmp_path):
        """测试保存和加载索引"""
        mock_config.vector_db.db_path = str(tmp_path)
        mock_config.vector_db.chunk_size = 2000
        mock_config.vector_db.chunk_overlap = 200

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1, 384)
        mock_get_model.return_value = mock_model

        # 创建并保存
        vs1 = VectorStore(1)
        vs1.add_documents([{"content": "持久化测试"}])

        # 重新加载
        vs2 = VectorStore(1)
        assert vs2.document_count == 1

    @patch("novel_agent.knowledge.vector_store.get_embedding_model")
    @patch("novel_agent.knowledge.vector_store.config")
    def test_cleanup(self, mock_config, mock_get_model, tmp_path):
        """测试清理功能"""
        mock_config.vector_db.db_path = str(tmp_path)
        mock_config.vector_db.chunk_size = 2000
        mock_config.vector_db.chunk_overlap = 200

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1, 384)
        mock_get_model.return_value = mock_model

        vs = VectorStore(1)
        # 添加超过限制的文档
        for i in range(2500):
            vs.add_documents([{"content": f"文档{i}"}])

        vs.cleanup(max_documents=2000)
        assert vs.document_count <= 2000


class TestVectorStoreSearch:
    """VectorStore搜索功能测试"""

    @patch("novel_agent.knowledge.vector_store.get_embedding_model")
    @patch("novel_agent.knowledge.vector_store.config")
    def test_search_with_filters(self, mock_config, mock_get_model, tmp_path):
        """测试带过滤器的搜索"""
        mock_config.vector_db.db_path = str(tmp_path)
        mock_config.vector_db.chunk_size = 2000
        mock_config.vector_db.chunk_overlap = 200

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1, 384)
        mock_get_model.return_value = mock_model

        vs = VectorStore(1)
        vs.add_documents([
            {"content": "第1章", "metadata": {"type": "chapter", "chapter_number": 1}},
            {"content": "第2章", "metadata": {"type": "chapter", "chapter_number": 2}},
            {"content": "知识", "metadata": {"type": "knowledge"}},
        ])

        # 按类型过滤
        results = vs.search("测试", filters={"type": "chapter"})
        assert len(results) == 2

        # 按章节号过滤
        results = vs.search("测试", filters={"chapter_number_lt": 2})
        assert len(results) == 1


class TestSimpleEncode:
    """简单编码降级方案测试"""

    @patch("novel_agent.knowledge.vector_store.get_embedding_model")
    @patch("novel_agent.knowledge.vector_store.config")
    def test_simple_encode(self, mock_config, mock_get_model, tmp_path):
        """测试简单编码在模型不可用时的降级"""
        mock_config.vector_db.db_path = str(tmp_path)
        mock_config.vector_db.chunk_size = 2000
        mock_config.vector_db.chunk_overlap = 200
        mock_get_model.return_value = None

        vs = VectorStore(1)
        vectors = vs._simple_encode(["测试文本1", "测试文本2"])

        assert vectors.shape[0] == 2
        assert vectors.shape[1] > 0
