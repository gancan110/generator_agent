"""
可扩展评估维度接口

提供插件化的评估维度，允许在不修改核心代码的情况下添加新的评估维度。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """评估结果数据类"""
    dimension: str          # 维度名称
    score: float            # 评分 (0-1)
    weight: float           # 权重
    details: Dict[str, Any] = None  # 详细信息
    issues: List[Dict] = None       # 发现的问题

    def __post_init__(self):
        if self.details is None:
            self.details = {}
        if self.issues is None:
            self.issues = []


class EvaluationDimension(ABC):
    """
    评估维度抽象基类
    
    所有评估维度必须继承此类并实现 evaluate 方法。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """维度名称"""
        pass

    @property
    @abstractmethod
    def weight(self) -> float:
        """维度权重 (0-1)"""
        pass

    @abstractmethod
    def evaluate(
        self,
        content: str,
        chapter_number: int = 0,
        context: Dict[str, Any] = None,
    ) -> EvaluationResult:
        """
        执行评估
        
        Args:
            content: 章节内容
            chapter_number: 章节号
            context: 额外上下文（如知识库、大纲等）
            
        Returns:
            评估结果
        """
        pass


class EvaluationRegistry:
    """
    评估维度注册表
    
    管理所有可用的评估维度，支持动态注册和查询。
    """

    _dimensions: Dict[str, EvaluationDimension] = {}
    _weights: Dict[str, float] = {}

    @classmethod
    def register(cls, dimension: EvaluationDimension, weight: float = None):
        """
        注册评估维度
        
        Args:
            dimension: 评估维度实例
            weight: 自定义权重（可选，覆盖维度默认权重）
        """
        cls._dimensions[dimension.name] = dimension
        if weight is not None:
            cls._weights[dimension.name] = weight
        logger.debug(f"已注册评估维度: {dimension.name} (权重: {weight or dimension.weight})")

    @classmethod
    def unregister(cls, name: str):
        """取消注册"""
        cls._dimensions.pop(name, None)
        cls._weights.pop(name, None)

    @classmethod
    def get_dimension(cls, name: str) -> Optional[EvaluationDimension]:
        """获取评估维度"""
        return cls._dimensions.get(name)

    @classmethod
    def get_all_dimensions(cls) -> Dict[str, EvaluationDimension]:
        """获取所有已注册的评估维度"""
        return cls._dimensions.copy()

    @classmethod
    def get_weight(cls, name: str) -> float:
        """获取维度权重"""
        if name in cls._weights:
            return cls._weights[name]
        dim = cls._dimensions.get(name)
        return dim.weight if dim else 0.0

    @classmethod
    def evaluate_all(
        cls,
        content: str,
        chapter_number: int = 0,
        context: Dict[str, Any] = None,
    ) -> Tuple[float, List[EvaluationResult]]:
        """
        执行所有评估维度并返回综合评分
        
        Args:
            content: 章节内容
            chapter_number: 章节号
            context: 额外上下文
            
        Returns:
            (综合评分, 各维度结果列表)
        """
        results = []
        total_weight = 0.0
        weighted_score_sum = 0.0

        for name, dimension in cls._dimensions.items():
            try:
                result = dimension.evaluate(content, chapter_number, context)
                results.append(result)
                
                weight = cls.get_weight(name)
                weighted_score_sum += result.score * weight
                total_weight += weight
            except Exception as e:
                logger.error(f"评估维度 {name} 执行失败: {e}")

        # 归一化评分
        if total_weight > 0:
            final_score = weighted_score_sum / total_weight
        else:
            final_score = 0.0

        return final_score, results

    @classmethod
    def clear(cls):
        """清空所有注册的维度"""
        cls._dimensions.clear()
        cls._weights.clear()
