"""
任务优先级队列

实现基于优先级的任务调度，支持任务依赖管理和状态监控。
"""

import heapq
import threading
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class TaskState(Enum):
    """任务状态"""
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(order=True)
class TaskItem:
    """
    任务项，支持优先级排序

    priority 值越小，优先级越高。
    """
    priority: int
    created_at: float = field(default_factory=time.time, compare=True)
    task_id: str = field(default="", compare=False)
    task_type: str = field(default="", compare=False)
    description: str = field(default="", compare=False)
    callback: Optional[Callable] = field(default=None, compare=False)
    args: tuple = field(default_factory=tuple, compare=False)
    kwargs: dict = field(default_factory=dict, compare=False)
    dependencies: List[str] = field(default_factory=list, compare=False)
    state: TaskState = field(default=TaskState.WAITING, compare=False)
    result: Any = field(default=None, compare=False)
    error: Optional[Exception] = field(default=None, compare=False)
    retry_count: int = field(default=0, compare=False)


class TaskQueue:
    """
    优先级任务队列

    功能：
    - 按优先级调度任务（高优先级先执行）
    - 任务状态追踪
    - 任务依赖管理
    - 线程安全
    """

    def __init__(self):
        self._queue: List[TaskItem] = []
        self._lock = threading.Lock()
        self._task_map: dict = {}  # task_id -> TaskItem
        self._completed_ids: set = set()

    def enqueue(self, task: TaskItem) -> str:
        """
        将任务加入队列

        Args:
            task: 任务项

        Returns:
            任务ID
        """
        with self._lock:
            heapq.heappush(self._queue, task)
            self._task_map[task.task_id] = task
            logger.info(f"任务入队: [{task.task_id}] {task.description} (优先级={task.priority})")
            return task.task_id

    def dequeue(self) -> Optional[TaskItem]:
        """
        取出下一个可执行的任务（优先级最高且依赖已满足）

        Returns:
            可执行的任务，如果没有可执行的任务则返回 None
        """
        with self._lock:
            # 遍历队列，找到第一个依赖已满足的任务
            for i, task in enumerate(self._queue):
                if task.state != TaskState.WAITING:
                    continue
                if self._dependencies_met(task):
                    # 从堆中移除并返回
                    self._queue.pop(i)
                    heapq.heapify(self._queue)
                    task.state = TaskState.RUNNING
                    return task
            return None

    def complete_task(self, task_id: str, result: Any = None):
        """标记任务完成"""
        with self._lock:
            if task_id in self._task_map:
                task = self._task_map[task_id]
                task.state = TaskState.COMPLETED
                task.result = result
                self._completed_ids.add(task_id)
                logger.info(f"任务完成: [{task_id}]")

    def fail_task(self, task_id: str, error: Exception):
        """标记任务失败"""
        with self._lock:
            if task_id in self._task_map:
                task = self._task_map[task_id]
                task.state = TaskState.FAILED
                task.error = error
                logger.error(f"任务失败: [{task_id}] - {error}")

    def retry_task(self, task_id: str):
        """将失败的任务重新入队"""
        with self._lock:
            if task_id in self._task_map:
                task = self._task_map[task_id]
                task.state = TaskState.WAITING
                task.retry_count += 1
                task.error = None
                heapq.heappush(self._queue, task)
                logger.info(f"任务重试: [{task_id}] (第 {task.retry_count} 次)")

    def get_task(self, task_id: str) -> Optional[TaskItem]:
        """获取任务信息"""
        return self._task_map.get(task_id)

    def _dependencies_met(self, task: TaskItem) -> bool:
        """检查任务的所有依赖是否已完成"""
        for dep_id in task.dependencies:
            if dep_id not in self._completed_ids:
                return False
        return True

    @property
    def size(self) -> int:
        """队列中的待处理任务数"""
        return len([t for t in self._queue if t.state == TaskState.WAITING])

    @property
    def is_empty(self) -> bool:
        """队列是否为空"""
        return self.size == 0

    def get_status_summary(self) -> dict:
        """获取任务状态摘要"""
        summary = {state: 0 for state in TaskState}
        for task in self._task_map.values():
            summary[task.state] += 1
        return {k.value: v for k, v in summary.items()}
