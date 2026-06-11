"""
任务执行器

负责任务的实际执行，包括并发控制和动态资源分配。
"""

import logging
import threading
import time
import uuid
from typing import Callable, Optional, Any, List
from concurrent.futures import ThreadPoolExecutor, Future

from novel_agent.config import config
from novel_agent.scheduler.queue import TaskQueue, TaskItem, TaskState
from novel_agent.scheduler.retry import RetryPolicy

logger = logging.getLogger(__name__)


class TaskExecutor:
    """
    任务执行器

    功能：
    - 从任务队列中取出任务并执行
    - 并发控制（限制同时执行的任务数）
    - 超时管理
    - 与重试策略集成
    """

    def __init__(self, task_queue: Optional[TaskQueue] = None):
        self.task_queue = task_queue or TaskQueue()
        self.retry_policy = RetryPolicy(
            max_retries=config.scheduler.max_retries,
            retry_delay=config.scheduler.retry_delay,
        )
        self._executor: Optional[ThreadPoolExecutor] = None
        self._running_futures: dict = {}  # task_id -> Future
        self._lock = threading.Lock()
        self._running = False

    @property
    def max_workers(self) -> int:
        return config.scheduler.max_workers

    def start(self):
        """启动执行器"""
        self._running = True
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        logger.info(f"任务执行器已启动，最大并发数: {self.max_workers}")

    def stop(self):
        """停止执行器"""
        self._running = False
        if self._executor:
            self._executor.shutdown(wait=True)
            logger.info("任务执行器已停止")

    def submit_task(
        self,
        task_type: str,
        description: str,
        callback: Callable,
        priority: int = 2,
        args: tuple = (),
        kwargs: dict = None,
        dependencies: List[str] = None,
    ) -> str:
        """
        提交新任务到队列

        Args:
            task_type: 任务类型
            description: 任务描述
            callback: 任务执行函数
            priority: 优先级（1=高, 2=中, 3=低）
            args: 位置参数
            kwargs: 关键字参数
            dependencies: 依赖的任务ID列表

        Returns:
            任务ID
        """
        task_id = f"{task_type}_{uuid.uuid4().hex[:8]}"
        task = TaskItem(
            priority=priority,
            task_id=task_id,
            task_type=task_type,
            description=description,
            callback=callback,
            args=args,
            kwargs=kwargs or {},
            dependencies=dependencies or [],
        )
        self.task_queue.enqueue(task)
        return task_id

    def execute_next(self) -> Optional[str]:
        """
        取出并执行下一个任务

        Returns:
            执行的任务ID，如果无可执行任务则返回 None
        """
        task = self.task_queue.dequeue()
        if not task:
            return None

        if not self._executor:
            self.start()

        future = self._executor.submit(self._execute_task, task)
        with self._lock:
            self._running_futures[task.task_id] = future

        return task.task_id

    def _execute_task(self, task: TaskItem):
        """执行单个任务"""
        logger.info(f"开始执行任务: [{task.task_id}] {task.description}")
        start_time = time.time()

        try:
            if task.callback:
                result = task.callback(*task.args, **task.kwargs)
            else:
                result = None

            elapsed = time.time() - start_time
            logger.info(f"任务完成: [{task.task_id}] 耗时 {elapsed:.2f}s")
            self.task_queue.complete_task(task.task_id, result)

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"任务异常: [{task.task_id}] 耗时 {elapsed:.2f}s 错误: {e}")

            # 检查是否可重试
            if self.retry_policy.should_retry(task.retry_count, e):
                logger.info(f"任务将重试: [{task.task_id}]")
                self.retry_policy.wait_before_retry(task.retry_count)
                self.task_queue.retry_task(task.task_id)
            else:
                self.task_queue.fail_task(task.task_id, e)

        finally:
            with self._lock:
                self._running_futures.pop(task.task_id, None)

    def run_all(self):
        """运行队列中所有任务直到完成"""
        if not self._executor:
            self.start()

        logger.info("开始执行所有任务...")
        while self._running and not self.task_queue.is_empty:
            task_id = self.execute_next()
            if task_id is None:
                # 没有可执行的任务（可能都在等待依赖）
                time.sleep(0.5)

        # 等待所有正在执行的任务完成
        self._wait_for_completion()
        logger.info("所有任务执行完成")

    def _wait_for_completion(self):
        """等待所有运行中的任务完成"""
        while True:
            with self._lock:
                if not self._running_futures:
                    break
            time.sleep(0.5)

    def get_status(self) -> dict:
        """获取执行器状态"""
        return {
            "running": self._running,
            "queue_size": self.task_queue.size,
            "active_tasks": len(self._running_futures),
            "task_summary": self.task_queue.get_status_summary(),
        }
