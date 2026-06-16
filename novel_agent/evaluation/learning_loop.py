"""
学习循环模块

从质量反馈中学习，自动优化生成策略。
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from novel_agent.config import config

logger = logging.getLogger(__name__)


@dataclass
class QualityFeedback:
    """质量反馈数据"""
    chapter_number: int
    score: float
    dimension_scores: Dict[str, float]
    issues: List[Dict]
    rewrite_applied: bool = False
    rewrite_improvement: float = 0.0


@dataclass
class StrategyAdjustment:
    """策略调整建议"""
    parameter: str
    current_value: float
    suggested_value: float
    reason: str
    confidence: float


class LearningLoop:
    """
    学习循环
    
    从质量反馈中学习，自动优化生成策略：
    1. 收集质量反馈
    2. 分析模式和趋势
    3. 生成策略调整建议
    4. 应用优化
    """

    def __init__(self, project_id: int):
        """
        Args:
            project_id: 项目 ID
        """
        self.project_id = project_id
        self._feedback_history: List[QualityFeedback] = []
        self._adjustments_history: List[StrategyAdjustment] = []
        self._learning_data_path = Path(config.output_dir) / f"project_{project_id}" / "learning_data.json"
        self._load_learning_data()

    def _load_learning_data(self):
        """加载学习数据"""
        if self._learning_data_path.exists():
            try:
                with open(self._learning_data_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._feedback_history = [
                        QualityFeedback(**fb) for fb in data.get("feedback", [])
                    ]
                    self._adjustments_history = [
                        StrategyAdjustment(**adj) for adj in data.get("adjustments", [])
                    ]
                logger.info(f"已加载 {len(self._feedback_history)} 条反馈记录")
            except Exception as e:
                logger.warning(f"加载学习数据失败: {e}")

    def _save_learning_data(self):
        """保存学习数据"""
        try:
            self._learning_data_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "feedback": [
                    {
                        "chapter_number": fb.chapter_number,
                        "score": fb.score,
                        "dimension_scores": fb.dimension_scores,
                        "issues": fb.issues,
                        "rewrite_applied": fb.rewrite_applied,
                        "rewrite_improvement": fb.rewrite_improvement,
                    }
                    for fb in self._feedback_history
                ],
                "adjustments": [
                    {
                        "parameter": adj.parameter,
                        "current_value": adj.current_value,
                        "suggested_value": adj.suggested_value,
                        "reason": adj.reason,
                        "confidence": adj.confidence,
                    }
                    for adj in self._adjustments_history
                ],
            }
            with open(self._learning_data_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("学习数据已保存")
        except Exception as e:
            logger.warning(f"保存学习数据失败: {e}")

    def record_feedback(self, feedback: QualityFeedback):
        """
        记录质量反馈
        
        Args:
            feedback: 质量反馈数据
        """
        self._feedback_history.append(feedback)
        self._save_learning_data()
        
        # 分析并生成调整建议
        adjustments = self._analyze_and_suggest()
        if adjustments:
            self._adjustments_history.extend(adjustments)
            self._save_learning_data()
            
            for adj in adjustments:
                logger.info(
                    f"策略调整建议: {adj.parameter} "
                    f"{adj.current_value:.2f} -> {adj.suggested_value:.2f} "
                    f"(原因: {adj.reason}, 置信度: {adj.confidence:.2f})"
                )

    def _analyze_and_suggest(self) -> List[StrategyAdjustment]:
        """分析反馈历史，生成策略调整建议"""
        if len(self._feedback_history) < 3:
            return []

        adjustments = []
        recent = self._feedback_history[-10:]  # 最近10条反馈

        # 1. 分析整体质量趋势
        scores = [fb.score for fb in recent]
        avg_score = sum(scores) / len(scores)
        trend = scores[-1] - scores[0] if len(scores) > 1 else 0

        # 2. 分析各维度表现
        dimension_scores = defaultdict(list)
        for fb in recent:
            for dim, score in fb.dimension_scores.items():
                dimension_scores[dim].append(score)

        # 3. 识别薄弱维度
        for dim, dim_scores in dimension_scores.items():
            avg_dim_score = sum(dim_scores) / len(dim_scores)
            if avg_dim_score < 0.6:
                # 薄弱维度，建议调整相关参数
                adjustments.extend(self._suggest_dimension_improvements(dim, avg_dim_score))

        # 4. 分析重写效果
        rewrite_feedbacks = [fb for fb in recent if fb.rewrite_applied]
        if rewrite_feedbacks:
            avg_improvement = sum(fb.rewrite_improvement for fb in rewrite_feedbacks) / len(rewrite_feedbacks)
            if avg_improvement < 0.1:
                # 重写效果不佳，建议调整重写策略
                adjustments.append(StrategyAdjustment(
                    parameter="rewrite_strategy",
                    current_value=0.7,  # 当前阈值
                    suggested_value=0.75,  # 提高阈值，减少无效重写
                    reason=f"重写效果不佳，平均提升仅 {avg_improvement:.2f}",
                    confidence=0.6,
                ))

        # 5. 质量趋势下降，建议降低创造性
        if trend < -0.1 and avg_score < 0.7:
            adjustments.append(StrategyAdjustment(
                parameter="chapter_temperature",
                current_value=config.generation.chapter_temperature,
                suggested_value=max(0.5, config.generation.chapter_temperature - 0.1),
                reason=f"质量趋势下降 (趋势: {trend:.2f})",
                confidence=0.7,
            ))

        return adjustments

    def _suggest_dimension_improvements(
        self, dimension: str, avg_score: float
    ) -> List[StrategyAdjustment]:
        """针对特定维度生成改进建议"""
        suggestions = []

        if dimension == "ai_traces":
            suggestions.append(StrategyAdjustment(
                parameter="ai_trace_penalty",
                current_value=0.3,
                suggested_value=0.35,
                reason=f"AI痕迹维度得分偏低 ({avg_score:.2f})",
                confidence=0.7,
            ))
        elif dimension == "dialogue":
            suggestions.append(StrategyAdjustment(
                parameter="dialogue_boost",
                current_value=1.0,
                suggested_value=1.2,
                reason=f"对话密度维度得分偏低 ({avg_score:.2f})",
                confidence=0.6,
            ))
        elif dimension == "style":
            suggestions.append(StrategyAdjustment(
                parameter="style_penalty",
                current_value=0.15,
                suggested_value=0.2,
                reason=f"写作风格维度得分偏低 ({avg_score:.2f})",
                confidence=0.6,
            ))

        return suggestions

    def get_strategy_summary(self) -> Dict:
        """获取策略摘要"""
        if not self._feedback_history:
            return {"status": "无反馈数据"}

        recent = self._feedback_history[-10:]
        scores = [fb.score for fb in recent]
        
        return {
            "total_feedback": len(self._feedback_history),
            "recent_avg_score": sum(scores) / len(scores),
            "score_trend": scores[-1] - scores[0] if len(scores) > 1 else 0,
            "total_adjustments": len(self._adjustments_history),
            "pending_adjustments": [
                {
                    "parameter": adj.parameter,
                    "suggested_value": adj.suggested_value,
                    "reason": adj.reason,
                }
                for adj in self._adjustments_history[-3:]
            ],
        }

    def get_optimal_parameters(self) -> Dict[str, float]:
        """根据学习历史返回最优参数"""
        if not self._adjustments_history:
            return {}

        # 聚合最近的调整建议
        param_suggestions = defaultdict(list)
        for adj in self._adjustments_history[-10:]:
            param_suggestions[adj.parameter].append(adj.suggested_value)

        # 取平均值
        optimal = {}
        for param, values in param_suggestions.items():
            optimal[param] = sum(values) / len(values)

        return optimal
