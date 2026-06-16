"""
数据库模型单元测试
"""

import pytest
from datetime import datetime

from novel_agent.database.models import (
    Project,
    WorldSetting,
    CharacterLibrary,
    ItemLibrary,
    PlotPoint,
    SuspenseManager,
    Outline,
    Chapter,
    TaskRecord,
    MemoryArchive,
    TaskStatus,
    TaskPriority,
    SuspenseLevelEnum,
    SuspenseStatusEnum,
    CharacterStatusEnum,
    ItemStatusEnum,
)


class TestProject:
    """Project模型测试"""

    def test_create_project(self):
        """测试创建项目"""
        project = Project()
        project.title = "测试小说"
        project.genre = "玄幻修仙"
        project.theme = "修仙"
        project.target_chapters = 100
        assert project.title == "测试小说"
        assert project.genre == "玄幻修仙"
        assert project.target_chapters == 100

    def test_project_defaults(self):
        """测试项目默认值"""
        project = Project()
        project.title = "测试"
        project.genre = "测试"
        assert project.target_chapters == 100


class TestCharacterLibrary:
    """CharacterLibrary模型测试"""

    def test_create_character(self):
        """测试创建角色"""
        char = CharacterLibrary()
        char.project_id = 1
        char.name = "主角"
        char.appearance = "英俊潇洒"
        char.personality = ["勇敢", "聪明"]
        assert char.name == "主角"
        assert char.appearance == "英俊潇洒"
        assert char.personality == ["勇敢", "聪明"]

    def test_character_status_enum(self):
        """测试角色状态枚举"""
        assert CharacterStatusEnum.ACTIVE.value == "active"
        assert CharacterStatusEnum.DEAD.value == "dead"
        assert CharacterStatusEnum.MISSING.value == "missing"
        assert CharacterStatusEnum.EXITED.value == "exited"


class TestItemLibrary:
    """ItemLibrary模型测试"""

    def test_create_item(self):
        """测试创建物品"""
        item = ItemLibrary()
        item.project_id = 1
        item.name = "神剑"
        item.item_type = "法宝"
        item.grade = "天阶上品"
        assert item.name == "神剑"
        assert item.item_type == "法宝"
        assert item.grade == "天阶上品"

    def test_item_status_enum(self):
        """测试物品状态枚举"""
        assert ItemStatusEnum.OWNED.value == "owned"
        assert ItemStatusEnum.DESTROYED.value == "destroyed"
        assert ItemStatusEnum.GIVEN.value == "given"
        assert ItemStatusEnum.LOST.value == "lost"
        assert ItemStatusEnum.TRANSFERRED.value == "transferred"


class TestSuspenseManager:
    """SuspenseManager模型测试"""

    def test_create_suspense(self):
        """测试创建悬念"""
        suspense = SuspenseManager()
        suspense.project_id = 1
        suspense.level = SuspenseLevelEnum.S
        suspense.title = "主线悬念"
        suspense.description = "主角身世之谜"
        suspense.introduced_chapter = 1
        assert suspense.level == SuspenseLevelEnum.S
        assert suspense.title == "主线悬念"

    def test_suspense_level_enum(self):
        """测试悬念等级枚举"""
        assert SuspenseLevelEnum.S.value == "S"
        assert SuspenseLevelEnum.A.value == "A"
        assert SuspenseLevelEnum.B.value == "B"

    def test_suspense_status_enum(self):
        """测试悬念状态枚举"""
        assert SuspenseStatusEnum.ACTIVE.value == "active"
        assert SuspenseStatusEnum.RESOLVED.value == "resolved"
        assert SuspenseStatusEnum.ABANDONED.value == "abandoned"


class TestChapter:
    """Chapter模型测试"""

    def test_create_chapter(self):
        """测试创建章节"""
        chapter = Chapter()
        chapter.project_id = 1
        chapter.chapter_number = 1
        chapter.title = "第一章"
        chapter.content = "章节内容..."
        chapter.word_count = 8000
        assert chapter.chapter_number == 1
        assert chapter.title == "第一章"
        assert chapter.word_count == 8000

    def test_chapter_defaults(self):
        """测试章节默认值"""
        chapter = Chapter()
        chapter.project_id = 1
        chapter.chapter_number = 1
        chapter.title = "测试"
        chapter.content = "内容"
        assert chapter.version == 1


class TestOutline:
    """Outline模型测试"""

    def test_create_outline(self):
        """测试创建大纲"""
        outline = Outline()
        outline.project_id = 1
        outline.phase = "initial"
        outline.chapter_start = 1
        outline.chapter_end = 50
        outline.content = "大纲内容..."
        assert outline.phase == "initial"
        assert outline.chapter_start == 1
        assert outline.chapter_end == 50


class TestTaskRecord:
    """TaskRecord模型测试"""

    def test_create_task(self):
        """测试创建任务"""
        task = TaskRecord()
        task.project_id = 1
        task.task_type = "chapter_generation"
        task.description = "生成第1章"
        assert task.task_type == "chapter_generation"
        assert task.priority == TaskPriority.MEDIUM
        assert task.status == TaskStatus.PENDING

    def test_task_status_enum(self):
        """测试任务状态枚举"""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.RETRYING.value == "retrying"

    def test_task_priority_enum(self):
        """测试任务优先级枚举"""
        assert TaskPriority.HIGH.value == 1
        assert TaskPriority.MEDIUM.value == 2
        assert TaskPriority.LOW.value == 3


class TestMemoryArchive:
    """MemoryArchive模型测试"""

    def test_create_archive(self):
        """测试创建记忆归档"""
        archive = MemoryArchive()
        archive.project_id = 1
        archive.archive_type = "volume_summary"
        archive.title = "第1-10章摘要"
        archive.content = "压缩后的摘要内容"
        archive.chapter_start = 1
        archive.chapter_end = 10
        assert archive.archive_type == "volume_summary"
        assert archive.chapter_start == 1
        assert archive.chapter_end == 10


class TestWorldSetting:
    """WorldSetting模型测试"""

    def test_create_world_setting(self):
        """测试创建世界设定"""
        setting = WorldSetting(
            project_id=1,
            category="力量体系",
            title="修仙境界",
            content="炼气、筑基、金丹...",
        )
        assert setting.category == "力量体系"
        assert setting.title == "修仙境界"


class TestPlotPoint:
    """PlotPoint模型测试"""

    def test_create_plot_point(self):
        """测试创建剧情节点"""
        point = PlotPoint()
        point.project_id = 1
        point.chapter_number = 1
        point.plot_type = "冲突"
        point.title = "主角与反派的第一次冲突"
        point.description = "详细描述..."
        assert point.plot_type == "冲突"
        assert point.is_resolved is False
