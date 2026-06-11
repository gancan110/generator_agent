"""
Agnes AI 小说生成Agent - 配置管理模块

集中管理所有配置项，包括API密钥、数据库连接、生成参数等。
通过环境变量或.env文件加载配置。
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# 加载 .env 文件
load_dotenv()

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


class LLMConfig(BaseModel):
    """LLM 模型配置"""
    api_key: str = Field(default_factory=lambda: os.getenv("AGNES_API_KEY", ""))
    base_url: str = Field(default_factory=lambda: os.getenv("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1"))
    model: str = Field(default_factory=lambda: os.getenv("AGNES_MODEL", "agnes-2.0-flash"))
    max_retries: int = 3
    timeout: int = 120


class MySQLConfig(BaseModel):
    """MySQL 数据库配置"""
    host: str = Field(default_factory=lambda: os.getenv("MYSQL_HOST", "localhost"))
    port: int = Field(default_factory=lambda: int(os.getenv("MYSQL_PORT", "3306")))
    user: str = Field(default_factory=lambda: os.getenv("MYSQL_USER", "root"))
    password: str = Field(default_factory=lambda: os.getenv("MYSQL_PASSWORD", "123456"))
    database: str = Field(default_factory=lambda: os.getenv("MYSQL_DATABASE", "agnes_novel"))

    @property
    def connection_url(self) -> str:
        """构建 SQLAlchemy 连接 URL"""
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
            f"?charset=utf8mb4"
        )


class GenerationConfig(BaseModel):
    """小说生成参数配置"""
    # 章节配置
    default_chapters: int = Field(default_factory=lambda: int(os.getenv("DEFAULT_CHAPTERS", "100")))
    words_per_chapter: int = Field(default_factory=lambda: int(os.getenv("WORDS_PER_CHAPTER", "8000")))
    words_per_segment: int = Field(default_factory=lambda: int(os.getenv("WORDS_PER_SEGMENT", "3000")))

    # Temperature 参数
    outline_temperature: float = 0.3       # 大纲生成（低温度保证结构化）
    chapter_temperature: float = 0.7       # 章节写作（较高温度增加创意）
    evaluation_temperature: float = 0.1    # 评估审计（低温度保证准确性）
    polish_temperature: float = 0.5        # 润色修改（中等温度）

    # 质量阈值
    quality_threshold: float = 0.7         # 低于此分数触发参数调整
    quality_high_threshold: float = 0.8    # 高于此分数可增加创造性

    # 大纲更新频率
    outline_update_interval: int = 5       # 每N章更新一次大纲


class VectorDBConfig(BaseModel):
    """向量数据库配置"""
    db_path: str = Field(default_factory=lambda: os.getenv("VECTOR_DB_PATH", "./vector_db"))
    chunk_size: int = 2000                 # 文档切片大小（字符数）
    chunk_overlap: int = 200               # 切片重叠字符数
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class SchedulerConfig(BaseModel):
    """任务调度器配置"""
    max_workers: int = 3                   # 最大并发任务数
    max_retries: int = 3                   # 任务最大重试次数
    retry_delay: float = 5.0              # 重试延迟（秒）
    task_timeout: int = 300               # 任务超时时间（秒）

    # 任务优先级
    priority_outline: int = 1             # 大纲生成（最高优先级）
    priority_chapter: int = 2             # 章节生成（中等优先级）
    priority_knowledge: int = 3           # 知识库更新（较低优先级）


class SkillConfig(BaseModel):
    """Skill 系统配置"""
    enable_auto_match: bool = True           # 是否自动根据 genre 匹配 Skill
    fallback_skill_id: str = "_base"         # 无匹配时的默认 Skill
    enable_project_overrides: bool = True    # 是否允许项目级覆盖
    cache_ttl: int = 3600                    # Skill 缓存过期时间（秒）
    enable_auto_generate: bool = True        # 无匹配时是否用 LLM 自动生成 Skill
    auto_generate_temperature: float = 0.3   # 自动生成 Skill 的温度（低温度保证结构化）


class AppConfig(BaseModel):
    """应用总配置，聚合所有子配置"""
    llm: LLMConfig = Field(default_factory=LLMConfig)
    mysql: MySQLConfig = Field(default_factory=MySQLConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    vector_db: VectorDBConfig = Field(default_factory=VectorDBConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    skill: SkillConfig = Field(default_factory=SkillConfig)

    # 日志配置
    log_dir: str = Field(default_factory=lambda: os.getenv("LOG_DIR", "./logs"))
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    # 输出目录
    output_dir: str = Field(default_factory=lambda: os.getenv("OUTPUT_DIR", "./output"))


# 全局配置单例
config = AppConfig()
