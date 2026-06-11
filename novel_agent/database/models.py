"""
数据库模型定义

定义所有 SQLAlchemy ORM 模型，对应 MySQL 中的数据表。
包括：世界观设定、角色档案、物品功法、剧情节点、悬念管理、大纲、章节等。
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Float,
    Enum, Boolean, ForeignKey, JSON
)
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()


# ==================== 枚举类型 ====================

class TaskStatus(enum.Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class TaskPriority(enum.Enum):
    """任务优先级"""
    HIGH = 1       # 大纲生成
    MEDIUM = 2     # 章节生成
    LOW = 3        # 知识库更新


class SuspenseLevelEnum(enum.Enum):
    """悬念等级"""
    S = "S"   # 主线悬念（贯穿全书）
    A = "A"   # 卷级悬念（当前地图核心谜团）
    B = "B"   # 章级悬念（短期可解决）


class SuspenseStatusEnum(enum.Enum):
    """悬念状态"""
    ACTIVE = "active"       # 活跃中
    RESOLVED = "resolved"   # 已解决
    ABANDONED = "abandoned" # 已放弃


class CharacterStatusEnum(enum.Enum):
    """角色状态"""
    ACTIVE = "active"       # 活跃
    DEAD = "dead"           # 已死亡
    MISSING = "missing"     # 失踪
    EXITED = "exited"       # 已退出故事


class ItemStatusEnum(enum.Enum):
    """物品状态"""
    OWNED = "owned"         # 主角持有
    DESTROYED = "destroyed" # 已损毁
    GIVEN = "given"         # 已送人
    LOST = "lost"           # 遗失
    TRANSFERRED = "transferred"  # 已转移


# ==================== 项目表 ====================

class Project(Base):
    """小说项目"""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False, comment="小说标题")
    genre = Column(String(100), nullable=False, comment="题材类型（如玄幻、都市）")
    theme = Column(String(255), comment="主题")
    description = Column(Text, comment="项目描述")
    target_chapters = Column(Integer, default=100, comment="目标章节数")
    current_chapter = Column(Integer, default=0, comment="当前生成到的章节")
    status = Column(String(50), default="created", comment="项目状态")
    skill_id = Column(String(100), comment="Skill标识符（如 xuanhuan_xianxia）")
    skill_overrides = Column(JSON, comment="项目级Skill覆盖配置")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    # 关联
    outlines = relationship("Outline", back_populates="project", cascade="all, delete-orphan")
    chapters = relationship("Chapter", back_populates="project", cascade="all, delete-orphan")
    world_settings = relationship("WorldSetting", back_populates="project", cascade="all, delete-orphan")
    characters = relationship("CharacterLibrary", back_populates="project", cascade="all, delete-orphan")
    items = relationship("ItemLibrary", back_populates="project", cascade="all, delete-orphan")
    plot_points = relationship("PlotPoint", back_populates="project", cascade="all, delete-orphan")
    suspense_records = relationship("SuspenseManager", back_populates="project", cascade="all, delete-orphan")
    tasks = relationship("TaskRecord", back_populates="project", cascade="all, delete-orphan")
    memory_archives = relationship("MemoryArchive", back_populates="project", cascade="all, delete-orphan")


# ==================== 世界观设定表 ====================

class WorldSetting(Base):
    """世界观设定"""
    __tablename__ = "world_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, comment="关联项目ID")
    category = Column(String(100), nullable=False, comment="设定类别（世界观/背景/规则/势力）")
    title = Column(String(255), nullable=False, comment="设定标题")
    content = Column(Text, nullable=False, comment="设定内容")
    metadata_json = Column(JSON, comment="额外元数据")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="world_settings")


# ==================== 角色档案表 ====================

class CharacterLibrary(Base):
    """角色档案库（人物卡）"""
    __tablename__ = "character_library"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, comment="关联项目ID")
    name = Column(String(100), nullable=False, comment="角色姓名")
    appearance = Column(Text, comment="外貌特征")
    personality = Column(JSON, comment="性格标签列表")
    cultivation_level = Column(String(100), comment="当前境界/实力等级")
    skills = Column(JSON, comment="技能/功法列表")
    core_items = Column(JSON, comment="核心法宝/装备")
    power_assessment = Column(Text, comment="战力评估")
    relationships = Column(JSON, comment="人际关系 {角色名: 关系描述}")
    highlight_moments = Column(JSON, comment="高光时刻列表")
    first_appearance = Column(Integer, comment="首次出场章节")
    last_appearance = Column(Integer, comment="最后出场章节")
    appearance_count = Column(Integer, default=0, comment="出场章节数")
    status = Column(
        Enum(CharacterStatusEnum),
        default=CharacterStatusEnum.ACTIVE,
        comment="角色状态"
    )
    notes = Column(Text, comment="备注")
    history = Column(JSON, comment="变化历史 [{chapter, changes, snapshot}]")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="characters")


# ==================== 物品与功法表 ====================

class ItemLibrary(Base):
    """物品与功法库（道具卡）"""
    __tablename__ = "item_library"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, comment="关联项目ID")
    name = Column(String(200), nullable=False, comment="物品/功法名称")
    item_type = Column(String(100), nullable=False, comment="类型（功法/法宝/丹药/材料等）")
    grade = Column(String(100), comment="品阶（如天阶上品）")
    acquisition_chapter = Column(Integer, comment="获取章节")
    acquisition_method = Column(Text, comment="获取途径")
    core_function = Column(Text, comment="核心作用")
    plot_significance = Column(Text, comment="剧情意义")
    current_holder = Column(String(100), comment="当前持有者")
    status = Column(
        Enum(ItemStatusEnum),
        default=ItemStatusEnum.OWNED,
        comment="物品状态"
    )
    metadata_json = Column(JSON, comment="额外元数据")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="items")


# ==================== 剧情节点表 ====================

class PlotPoint(Base):
    """剧情节点"""
    __tablename__ = "plot_points"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, comment="关联项目ID")
    chapter_number = Column(Integer, comment="关联章节号")
    plot_type = Column(String(100), nullable=False, comment="剧情类型（冲突/转折/高潮/伏笔等）")
    title = Column(String(255), nullable=False, comment="节点标题")
    description = Column(Text, nullable=False, comment="节点描述")
    characters_involved = Column(JSON, comment="涉及角色列表")
    consequences = Column(Text, comment="后续影响")
    is_resolved = Column(Boolean, default=False, comment="是否已解决")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="plot_points")


# ==================== 悬念管理表 ====================

class SuspenseManager(Base):
    """悬念管理器"""
    __tablename__ = "suspense_manager"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, comment="关联项目ID")
    level = Column(
        Enum(SuspenseLevelEnum),
        nullable=False,
        comment="悬念等级: S(主线)/A(卷级)/B(章级)"
    )
    title = Column(String(255), nullable=False, comment="悬念标题")
    description = Column(Text, nullable=False, comment="悬念描述")
    introduced_chapter = Column(Integer, nullable=False, comment="引入章节")
    expected_resolve_chapter = Column(Integer, comment="预计解决章节")
    actual_resolve_chapter = Column(Integer, comment="实际解决章节")
    resolution = Column(Text, comment="解决方式描述")
    status = Column(
        Enum(SuspenseStatusEnum),
        default=SuspenseStatusEnum.ACTIVE,
        comment="悬念状态"
    )
    related_characters = Column(JSON, comment="相关角色")
    related_items = Column(JSON, comment="相关物品")
    hints_planted = Column(JSON, comment="已埋下的线索")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="suspense_records")


# ==================== 大纲表 ====================

class Outline(Base):
    """小说大纲"""
    __tablename__ = "outlines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, comment="关联项目ID")
    phase = Column(String(50), nullable=False, comment="阶段: initial/update")
    chapter_start = Column(Integer, nullable=False, comment="起始章节")
    chapter_end = Column(Integer, nullable=False, comment="结束章节")
    content = Column(Text, nullable=False, comment="大纲内容")
    summary = Column(Text, comment="大纲摘要")
    key_events = Column(JSON, comment="关键事件列表")
    suspense_points = Column(JSON, comment="悬念点列表")
    version = Column(Integer, default=1, comment="版本号")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="outlines")


# ==================== 章节表 ====================

class Chapter(Base):
    """章节内容"""
    __tablename__ = "chapters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, comment="关联项目ID")
    chapter_number = Column(Integer, nullable=False, comment="章节序号")
    title = Column(String(255), nullable=False, comment="章节标题")
    content = Column(Text, nullable=False, comment="章节正文")
    word_count = Column(Integer, default=0, comment="字数统计")
    summary = Column(Text, comment="章节摘要")
    quality_score = Column(Float, comment="质量评分")
    quality_details = Column(JSON, comment="质量评估详情")
    new_characters = Column(JSON, comment="新出场角色")
    new_items = Column(JSON, comment="新出现物品")
    new_suspense = Column(JSON, comment="新增悬念")
    resolved_suspense = Column(JSON, comment="解决的悬念")
    version = Column(Integer, default=1, comment="版本号")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="chapters")


# ==================== 任务记录表 ====================

class TaskRecord(Base):
    """任务记录"""
    __tablename__ = "task_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, comment="关联项目ID")
    task_type = Column(String(100), nullable=False, comment="任务类型")
    description = Column(Text, comment="任务描述")
    priority = Column(Enum(TaskPriority), default=TaskPriority.MEDIUM, comment="优先级")
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, comment="任务状态")
    retry_count = Column(Integer, default=0, comment="重试次数")
    error_message = Column(Text, comment="错误信息")
    started_at = Column(DateTime, comment="开始时间")
    completed_at = Column(DateTime, comment="完成时间")
    result = Column(Text, comment="任务结果")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="tasks")


# ==================== 记忆归档表 ====================

class MemoryArchive(Base):
    """
    分层记忆归档

    存储压缩后的长期记忆，按类型分为：
    - volume_summary: 卷摘要（每10章压缩为一段）
    - character_arc: 角色弧线（关键转折归档）
    - world_change: 世界设定变更日志
    - suspense_archive: 已解决悬念归档（防止重复）
    """
    __tablename__ = "memory_archive"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, comment="关联项目ID")
    archive_type = Column(
        String(50), nullable=False,
        comment="归档类型: volume_summary/character_arc/world_change/suspense_archive"
    )
    title = Column(String(255), comment="归档标题")
    content = Column(Text, nullable=False, comment="归档内容（压缩后的文本）")
    chapter_start = Column(Integer, comment="覆盖起始章节")
    chapter_end = Column(Integer, comment="覆盖结束章节")
    token_estimate = Column(Integer, default=0, comment="预估 token 数")
    metadata_json = Column(JSON, comment="额外元数据")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="memory_archives")
