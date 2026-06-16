"""
测试配置和共享fixtures
"""

import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 设置测试环境变量
os.environ["MYSQL_HOST"] = "localhost"
os.environ["MYSQL_PORT"] = "3306"
os.environ["MYSQL_USER"] = "test_user"
os.environ["MYSQL_PASSWORD"] = "test_password"
os.environ["MYSQL_DATABASE"] = "test_novel"
os.environ["AGNES_API_KEY"] = "test_api_key"
os.environ["AGNES_BASE_URL"] = "https://test.api.com/v1"
os.environ["AGNES_MODEL"] = "test-model"
os.environ["VECTOR_DB_PATH"] = "./test_vector_db"
os.environ["LOG_DIR"] = "./test_logs"
os.environ["OUTPUT_DIR"] = "./test_output"


@pytest.fixture
def mock_llm_client():
    """模拟LLM客户端"""
    with patch("novel_agent.utils.llm_client.llm_client") as mock:
        mock.generate.return_value = "测试生成内容"
        mock.generate_stream.return_value = iter(["测试", "流式", "内容"])
        yield mock


@pytest.fixture
def mock_db_client():
    """模拟数据库客户端"""
    with patch("novel_agent.database.mysql_client.db_client") as mock:
        mock.init_db.return_value = None
        mock.add.return_value = 1
        mock.get_by_id.return_value = MagicMock(id=1, title="测试项目")
        mock.update.return_value = None
        mock.get_all.return_value = []
        yield mock


@pytest.fixture
def sample_config():
    """示例配置"""
    from novel_agent.config import AppConfig
    return AppConfig()


@pytest.fixture
def temp_dir(tmp_path):
    """临时目录"""
    return tmp_path
