"""
参数优化器单元测试
"""

import pytest

from novel_agent.evaluation.optimizer import ParameterOptimizer


class TestParameterOptimizer:
    """ParameterOptimizer类测试"""

    def test_init(self):
        """测试初始化"""
        optimizer = ParameterOptimizer()
        assert optimizer is not None

    def test_adjust_with_high_score(self):
        """测试高分调整"""
        optimizer = ParameterOptimizer()
        # 高分应该增加创造性
        optimizer.adjust(0.9)
        # 不应抛出异常

    def test_adjust_with_low_score(self):
        """测试低分调整"""
        optimizer = ParameterOptimizer()
        # 低分应该降低创造性
        optimizer.adjust(0.3)
        # 不应抛出异常

    def test_adjust_with_medium_score(self):
        """测试中等分数调整"""
        optimizer = ParameterOptimizer()
        optimizer.adjust(0.7)
        # 不应抛出异常

    def test_multiple_adjustments(self):
        """测试多次调整"""
        optimizer = ParameterOptimizer()
        scores = [0.9, 0.8, 0.3, 0.7, 0.95]
        for score in scores:
            optimizer.adjust(score)
        # 不应抛出异常
