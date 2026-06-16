"""
质量评估器单元测试
"""

import pytest
from unittest.mock import MagicMock, patch

from novel_agent.evaluation.quality import QualityEvaluator


class TestQualityEvaluator:
    """QualityEvaluator类测试"""

    def test_init(self):
        """测试初始化"""
        evaluator = QualityEvaluator(genre="玄幻修仙")
        assert evaluator.genre == "玄幻修仙"

    @patch("novel_agent.evaluation.quality.llm_client")
    def test_evaluate(self, mock_llm):
        """测试评估功能"""
        mock_llm.generate.return_value = '''
        {
            "overall_score": 0.85,
            "dimensions": {
                "plot": 0.8,
                "character": 0.9,
                "style": 0.85
            },
            "issues": [],
            "suggestions": ["建议1"]
        }
        '''

        evaluator = QualityEvaluator(genre="玄幻修仙")
        score = evaluator.evaluate(
            content="测试章节内容",
            chapter_number=1,
        )

        assert isinstance(score, float)
        assert 0 <= score <= 1

    def test_needs_rewrite(self):
        """测试是否需要重写"""
        evaluator = QualityEvaluator(genre="玄幻修仙")
        evaluator.last_details = {"needs_rewrite": True}
        assert evaluator.needs_rewrite() is True

        evaluator.last_details = {"needs_rewrite": False}
        assert evaluator.needs_rewrite() is False

    def test_diagnose(self):
        """测试诊断功能"""
        evaluator = QualityEvaluator(genre="玄幻修仙")
        evaluator.last_issues = [{"issue": "问题1"}, {"issue": "问题2"}]

        result = evaluator.diagnose()
        assert isinstance(result, list)

    def test_get_last_report(self):
        """测试获取最后报告"""
        evaluator = QualityEvaluator(genre="玄幻修仙")
        evaluator.last_details = {"total": 0.85, "plot": 0.8}

        report = evaluator.get_last_report()
        assert isinstance(report, dict)
        assert "total" in report


class TestQualityEvaluatorThresholds:
    """质量评估器阈值测试"""

    def test_rewrite_threshold(self):
        """测试重写阈值"""
        evaluator = QualityEvaluator(genre="玄幻修仙")
        assert evaluator.REWRITE_THRESHOLD == 0.70

    def test_score_range(self):
        """测试分数范围"""
        evaluator = QualityEvaluator(genre="玄幻修仙")

        # 模拟低分
        evaluator.last_details = {"needs_rewrite": True}
        assert evaluator.needs_rewrite() is True

        # 模拟高分
        evaluator.last_details = {"needs_rewrite": False}
        assert evaluator.needs_rewrite() is False
