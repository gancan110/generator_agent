"""
动态参数优化器

根据质量评估结果，动态调整后续生成的参数，
包括 temperature、检索深度等。
"""

import logging
from typing import Dict, Optional

from novel_agent.config import config

logger = logging.getLogger(__name__)


class ParameterOptimizer:
    """
    动态参数优化器

    根据质量评分自动调整生成策略：
    - 低分（<0.6）：降低温度，增加确定性，加深检索
    - 中分（0.6-0.8）：保持当前参数
    - 高分（>0.8）：适当增加创造性
    """

    def __init__(self):
        self._current_temperature = config.generation.chapter_temperature
        self._retrieval_depth_bonus = 0
        self._adjustment_history = []

    @property
    def current_temperature(self) -> float:
        """当前章节生成温度"""
        return self._current_temperature

    @property
    def retrieval_depth_bonus(self) -> int:
        """额外的检索深度"""
        return self._retrieval_depth_bonus

    def adjust(self, quality_score: float) -> Dict[str, float]:
        """
        根据质量评分调整参数

        Args:
            quality_score: 质量评分（0-1）

        Returns:
            调整后的参数字典
        """
        adjustment = {
            "previous_temperature": self._current_temperature,
            "quality_score": quality_score,
        }

        low_threshold = config.generation.quality_threshold
        high_threshold = config.generation.quality_high_threshold

        if quality_score < low_threshold - 0.1:
            # 严重低分：大幅降低温度，增加检索深度
            self._current_temperature = max(0.3, self._current_temperature - 0.2)
            self._retrieval_depth_bonus = min(5, self._retrieval_depth_bonus + 2)
            logger.info(
                f"质量评分较低 ({quality_score:.2f})，"
                f"降低温度至 {self._current_temperature:.2f}，"
                f"增加检索深度 +{self._retrieval_depth_bonus}"
            )

        elif quality_score < low_threshold:
            # 轻微低分：小幅降低温度
            self._current_temperature = max(0.4, self._current_temperature - 0.1)
            self._retrieval_depth_bonus = min(3, self._retrieval_depth_bonus + 1)
            logger.info(
                f"质量评分偏低 ({quality_score:.2f})，"
                f"调整温度至 {self._current_temperature:.2f}"
            )

        elif quality_score > high_threshold:
            # 高分：适当增加创造性
            self._current_temperature = min(0.9, self._current_temperature + 0.05)
            self._retrieval_depth_bonus = max(0, self._retrieval_depth_bonus - 1)
            logger.info(
                f"质量评分优秀 ({quality_score:.2f})，"
                f"适当增加创造性，温度 {self._current_temperature:.2f}"
            )

        else:
            # 正常范围：缓慢回归默认值
            default_temp = config.generation.chapter_temperature
            if self._current_temperature < default_temp:
                self._current_temperature = min(
                    default_temp, self._current_temperature + 0.05
                )
            if self._retrieval_depth_bonus > 0:
                self._retrieval_depth_bonus -= 1

        adjustment["new_temperature"] = self._current_temperature
        adjustment["retrieval_depth_bonus"] = self._retrieval_depth_bonus

        self._adjustment_history.append(adjustment)
        return adjustment

    def get_history(self):
        """获取参数调整历史"""
        return self._adjustment_history

    def reset(self):
        """重置为默认参数"""
        self._current_temperature = config.generation.chapter_temperature
        self._retrieval_depth_bonus = 0
        self._adjustment_history = []
