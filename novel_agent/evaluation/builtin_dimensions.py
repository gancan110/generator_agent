"""
内置评估维度

将现有的评估逻辑封装为可插拔的维度。
"""

import re
import logging
from typing import Any, Dict, List, Tuple

from .dimensions import EvaluationDimension, EvaluationResult, EvaluationRegistry

logger = logging.getLogger(__name__)


class AITraceDimension(EvaluationDimension):
    """AI痕迹检测维度"""

    # AI痕迹模式（从 quality.py 迁移）
    AI_TRACE_PATTERNS = [
        (r"嘴角勾起.{0,6}弧度", "嘴角勾起弧度", 3),
        (r"眼中闪过一丝", "眼中闪过一丝", 3),
        (r"如.{1,4}般", "如X般明喻", 1),
        (r"猛地", "猛地", 1),
        (r"游戏.{0,4}才刚刚开始", "游戏才刚开始", 5),
        (r"命运.{0,6}由我.{0,4}(定|掌控|主宰)", "命运金句", 5),
        (r"在这个.{2,10}的世界里", "在这个世界里", 4),
        (r"并没有.{2,15}[，,]也没有", "并没有也没有", 4),
        (r"带来了.{2,10}[。\.]\s*\n\s*带来了", "排比收束", 4),
        (r"如同一只.{2,6}的(蝙蝠|鹰|狼|虎)", "陈词比喻", 3),
        (r"断线的风筝", "断线风筝", 3),
        (r"如潮水般", "如潮水般", 2),
        (r"如鬼魅般", "如鬼魅般", 2),
        (r"冷冷道|淡淡道|冷笑道", "模板对话标签", 1),
        (r"像.{1,8}一[样本]", "像X一样明喻", 1),
        (r"一抹.{0,4}(微笑|笑意|弧度)", "一抹微笑", 2),
        (r"眸中.{0,6}(闪过|掠过|浮现)", "眸中闪过", 2),
        (r"内心深处.{0,6}(涌起|泛起|升起)", "内心深处涌起", 2),
        (r"不由自主.{0,6}(地)?(露出|浮现|涌起)", "不由自主", 1),
        (r"不自觉.{0,6}(地)?(露出|浮现|涌起)", "不自觉", 1),
    ]

    @property
    def name(self) -> str:
        return "ai_traces"

    @property
    def weight(self) -> float:
        return 0.30

    def evaluate(
        self,
        content: str,
        chapter_number: int = 0,
        context: Dict[str, Any] = None,
    ) -> EvaluationResult:
        """检测AI痕迹"""
        hits = []
        penalty = 0.0

        for pattern, desc, severity in self.AI_TRACE_PATTERNS:
            matches = re.findall(pattern, content)
            if matches:
                count = len(matches)
                hits.append({
                    "pattern": desc,
                    "count": count,
                    "severity": severity,
                })
                # 每次命中扣分，最多扣0.5
                penalty += min(0.05 * count * severity, 0.5)

        # 基础分1.0，按命中扣分
        score = max(0.0, 1.0 - penalty)

        # 诊断问题
        issues = []
        if hits:
            top_hits = sorted(hits, key=lambda x: x["count"] * x["severity"], reverse=True)[:3]
            issues.append({
                "dimension": self.name,
                "severity": "high" if score < 0.5 else "medium",
                "reason": f"AI痕迹过多（评分{score:.2f}）",
                "details": top_hits,
                "fix_hint": "减少AI高频词，增加自然表达",
            })

        return EvaluationResult(
            dimension=self.name,
            score=score,
            weight=self.weight,
            details={"hits": hits, "penalty": penalty},
            issues=issues,
        )


class DialogueDimension(EvaluationDimension):
    """对话密度检测维度"""

    @property
    def name(self) -> str:
        return "dialogue"

    @property
    def weight(self) -> float:
        return 0.15

    def evaluate(
        self,
        content: str,
        chapter_number: int = 0,
        context: Dict[str, Any] = None,
    ) -> EvaluationResult:
        """检测对话密度"""
        # 统计对话内容（引号内的内容）
        dialogue_matches = re.findall(r'[""「」『』【】](.*?)[""「」『』【】]', content)
        dialogue_chars = sum(len(m) for m in dialogue_matches)
        total_chars = len(content)
        
        if total_chars == 0:
            ratio = 0.0
        else:
            ratio = (dialogue_chars / total_chars) * 100

        # 对话密度评分：理想区间 15%-40%
        if 15 <= ratio <= 40:
            score = 1.0
        elif 10 <= ratio < 15 or 40 < ratio <= 50:
            score = 0.8
        elif 5 <= ratio < 10 or 50 < ratio <= 60:
            score = 0.6
        else:
            score = 0.4

        issues = []
        if ratio < 10:
            issues.append({
                "dimension": self.name,
                "severity": "medium",
                "reason": f"对话密度偏低（{ratio:.1f}%）",
                "fix_hint": "增加角色对话，提升互动感",
            })
        elif ratio > 60:
            issues.append({
                "dimension": self.name,
                "severity": "medium",
                "reason": f"对话密度过高（{ratio:.1f}%）",
                "fix_hint": "增加叙述和描写，平衡节奏",
            })

        return EvaluationResult(
            dimension=self.name,
            score=score,
            weight=self.weight,
            details={"ratio": ratio, "dialogue_chars": dialogue_chars, "total_chars": total_chars},
            issues=issues,
        )


class StyleDimension(EvaluationDimension):
    """写作风格维度"""

    @property
    def name(self) -> str:
        return "style"

    @property
    def weight(self) -> float:
        return 0.15

    def evaluate(
        self,
        content: str,
        chapter_number: int = 0,
        context: Dict[str, Any] = None,
    ) -> EvaluationResult:
        """评估写作风格"""
        issues = []
        score = 1.0

        # 检查段落长度
        paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
        if paragraphs:
            avg_para_len = sum(len(p) for p in paragraphs) / len(paragraphs)
            if avg_para_len > 300:
                score -= 0.1
                issues.append({
                    "dimension": self.name,
                    "severity": "low",
                    "reason": f"段落平均长度过长（{avg_para_len:.0f}字）",
                    "fix_hint": "适当分段，提升可读性",
                })

        # 检查句子长度
        sentences = re.split(r'[。！？]', content)
        sentences = [s.strip() for s in sentences if s.strip()]
        if sentences:
            avg_sent_len = sum(len(s) for s in sentences) / len(sentences)
            if avg_sent_len > 80:
                score -= 0.1
                issues.append({
                    "dimension": self.name,
                    "severity": "low",
                    "reason": f"句子平均长度过长（{avg_sent_len:.0f}字）",
                    "fix_hint": "适当断句，增加节奏感",
                })

        # 检查重复用词
        words = list(content)
        if len(words) > 100:
            # 简单检查：统计常见连接词频率
            connectors = ['然而', '但是', '不过', '于是', '因此', '所以']
            for conn in connectors:
                count = content.count(conn)
                if count > 5:
                    score -= 0.05
                    issues.append({
                        "dimension": self.name,
                        "severity": "low",
                        "reason": f"'{conn}' 出现 {count} 次，略显频繁",
                        "fix_hint": f"变换表达方式，避免重复使用'{conn}'",
                    })

        score = max(0.0, score)

        return EvaluationResult(
            dimension=self.name,
            score=score,
            weight=self.weight,
            details={"paragraph_count": len(paragraphs), "sentence_count": len(sentences)},
            issues=issues,
        )


def register_builtin_dimensions():
    """注册所有内置评估维度"""
    EvaluationRegistry.register(AITraceDimension())
    EvaluationRegistry.register(DialogueDimension())
    EvaluationRegistry.register(StyleDimension())
    logger.info("已注册内置评估维度: ai_traces, dialogue, style")
