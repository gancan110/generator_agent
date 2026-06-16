"""
配置管理模块单元测试
"""

import os
import pytest
from unittest.mock import patch

from novel_agent.config import (
    LLMConfig,
    MySQLConfig,
    GenerationConfig,
    VectorDBConfig,
    SchedulerConfig,
    SkillConfig,
    AppConfig,
)


class TestLLMConfig:
    """LLM配置测试"""

    def test_default_values(self):
        """测试默认值"""
        with patch.dict(os.environ, {
            "AGNES_API_KEY": "test_key",
            "AGNES_BASE_URL": "https://test.com/v1",
            "AGNES_MODEL": "test-model",
        }):
            config = LLMConfig()
            assert config.api_key == "test_key"
            assert config.base_url == "https://test.com/v1"
            assert config.model == "test-model"
            assert config.max_retries == 3
            assert config.timeout == 120

    def test_empty_env_uses_defaults(self):
        """测试空环境变量使用默认值"""
        with patch.dict(os.environ, {}, clear=True):
            config = LLMConfig()
            assert config.base_url == "https://apihub.agnes-ai.com/v1"
            assert config.model == "agnes-2.0-flash"


class TestMySQLConfig:
    """MySQL配置测试"""

    def test_connection_url(self):
        """测试连接URL构建"""
        with patch.dict(os.environ, {
            "MYSQL_HOST": "db.example.com",
            "MYSQL_PORT": "3307",
            "MYSQL_USER": "admin",
            "MYSQL_PASSWORD": "secret123",
            "MYSQL_DATABASE": "mydb",
        }):
            config = MySQLConfig()
            url = config.connection_url
            assert "db.example.com" in url
            assert "3307" in url
            assert "admin" in url
            assert "mydb" in url
            assert "charset=utf8mb4" in url


class TestGenerationConfig:
    """生成配置测试"""

    def test_default_chapters(self):
        """测试默认章节数"""
        with patch.dict(os.environ, {"DEFAULT_CHAPTERS": "50"}):
            config = GenerationConfig()
            assert config.default_chapters == 50

    def test_temperature_values(self):
        """测试温度参数"""
        config = GenerationConfig()
        assert config.outline_temperature == 0.3
        assert config.chapter_temperature == 0.7
        assert config.evaluation_temperature == 0.1

    def test_quality_thresholds(self):
        """测试质量阈值"""
        config = GenerationConfig()
        assert config.quality_threshold == 0.7
        assert config.rewrite_threshold == 0.70

    def test_memory_budgets(self):
        """测试记忆预算"""
        config = GenerationConfig()
        assert config.memory_budget_permanent == 3000
        assert config.memory_budget_working == 4500
        assert config.memory_budget_short_term == 6000
        assert config.memory_budget_long_term == 4500


class TestVectorDBConfig:
    """向量数据库配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = VectorDBConfig()
        assert config.chunk_size == 2000
        assert config.chunk_overlap == 200
        assert "paraphrase-multilingual" in config.embedding_model

    def test_custom_path(self):
        """测试自定义路径"""
        with patch.dict(os.environ, {"VECTOR_DB_PATH": "/custom/path"}):
            config = VectorDBConfig()
            assert config.db_path == "/custom/path"


class TestSchedulerConfig:
    """调度器配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = SchedulerConfig()
        assert config.max_workers == 3
        assert config.max_retries == 3
        assert config.retry_delay == 5.0
        assert config.task_timeout == 300

    def test_priorities(self):
        """测试优先级设置"""
        config = SchedulerConfig()
        assert config.priority_outline == 1
        assert config.priority_chapter == 2
        assert config.priority_knowledge == 3


class TestSkillConfig:
    """Skill配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = SkillConfig()
        assert config.enable_auto_match is True
        assert config.fallback_skill_id == "_base"
        assert config.cache_ttl == 3600

    def test_auto_generate(self):
        """测试自动生成配置"""
        config = SkillConfig()
        assert config.enable_auto_generate is True
        assert config.auto_generate_temperature == 0.3


class TestAppConfig:
    """应用总配置测试"""

    def test_aggregates_all_configs(self):
        """测试聚合所有子配置"""
        config = AppConfig()
        assert hasattr(config, "llm")
        assert hasattr(config, "mysql")
        assert hasattr(config, "generation")
        assert hasattr(config, "vector_db")
        assert hasattr(config, "scheduler")
        assert hasattr(config, "skill")

    def test_singleton_behavior(self):
        """测试单例行为"""
        from novel_agent.config import config as config1
        from novel_agent.config import config as config2
        assert config1 is config2

    def test_log_config(self):
        """测试日志配置"""
        config = AppConfig()
        assert config.log_level == "INFO"
