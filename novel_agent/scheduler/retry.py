"""
重试策略

实现任务失败后的自动重试机制，支持指数退避和最大重试次数。
"""

import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RetryPolicy:
    """
    重试策略

    功能：
    - 最大重试次数限制
    - 指数退避延迟
    - 可配置的异常过滤
    """

    def __init__(
        self,
        max_retries: int = 3,
        retry_delay: float = 5.0,
        backoff_factor: float = 2.0,
        max_delay: float = 60.0,
    ):
        """
        Args:
            max_retries: 最大重试次数
            retry_delay: 初始重试延迟（秒）
            backoff_factor: 退避因子（每次重试延迟乘以此值）
            max_delay: 最大重试延迟（秒）
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.backoff_factor = backoff_factor
        self.max_delay = max_delay

    def should_retry(self, current_retry_count: int, error: Optional[Exception] = None) -> bool:
        """
        判断是否应该重试

        Args:
            current_retry_count: 当前已重试次数
            error: 导致失败的异常

        Returns:
            是否应该重试
        """
        if current_retry_count >= self.max_retries:
            logger.warning(f"已达最大重试次数 ({self.max_retries})，不再重试")
            return False

        # 不可重试的异常类型
        non_retryable = (KeyboardInterrupt, SystemExit)
        if isinstance(error, non_retryable):
            logger.warning(f"不可重试的异常类型: {type(error).__name__}")
            return False

        return True

    def get_delay(self, retry_count: int) -> float:
        """
        计算当前重试的等待时间（指数退避）

        Args:
            retry_count: 当前重试次数

        Returns:
            等待时间（秒）
        """
        delay = self.retry_delay * (self.backoff_factor ** retry_count)
        return min(delay, self.max_delay)

    def wait_before_retry(self, retry_count: int):
        """
        在重试前等待一段时间

        Args:
            retry_count: 当前重试次数
        """
        delay = self.get_delay(retry_count)
        logger.info(f"重试前等待 {delay:.1f} 秒 (第 {retry_count + 1} 次重试)")
        time.sleep(delay)
