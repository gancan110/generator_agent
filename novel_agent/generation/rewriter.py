"""
章节重写器

当质量评估分数低于阈值时，根据诊断原因生成针对性的重写提示，
重新生成章节内容。记录重写历史和低分原因。
"""

import logging
from typing import Dict, List, Optional

from novel_agent.utils.llm_client import llm_client
from novel_agent.config import config
from novel_agent.database.mysql_client import db_client
from novel_agent.database.models import Chapter

logger = logging.getLogger(__name__)


class ChapterRewriter:
    """
    章节重写器
    
    功能：
    1. 根据评估诊断结果，构建针对性重写提示
    2. 重新调用 LLM 生成改进版内容
    3. 记录重写历史（原始分数、原因、重写后分数）
    4. 更新数据库中的章节记录
    """

    MAX_REWRITES = 1  # 每章最多重写 1 次（避免无限循环）

    def __init__(self, project_id: int):
        self.project_id = project_id
        self.rewrite_history: List[Dict] = []

    def should_rewrite(self, score: float, issues: List[Dict]) -> bool:
        """判断是否需要重写"""
        return score < config.generation.quality_threshold and len(issues) > 0

    def rewrite(
        self,
        chapter_number: int,
        chapter_outline: Dict,
        original_content: str,
        original_score: float,
        issues: List[Dict],
        system_prompt: str,
        knowledge_context: Dict[str, str],
        previous_chapter_summary: str = "",
    ) -> Optional[Dict]:
        """
        重写章节内容。

        Args:
            chapter_number: 章节序号
            chapter_outline: 章节大纲
            original_content: 原始内容
            original_score: 原始评分
            issues: 诊断出的问题列表
            system_prompt: 原始系统提示
            knowledge_context: 知识库上下文
            previous_chapter_summary: 上一章摘要

        Returns:
            重写后的章节数据，失败返回 None
        """
        logger.info(
            f"第 {chapter_number} 章触发重写 "
            f"(原评分 {original_score:.2f}, 问题数 {len(issues)})"
        )

        # 构建重写提示（包含原始问题和改进方向）
        rewrite_prompt = self._build_rewrite_prompt(
            chapter_number=chapter_number,
            chapter_outline=chapter_outline,
            original_content=original_content,
            issues=issues,
        )

        # 增强系统提示（追加重写指导）
        enhanced_system = system_prompt + self._build_rewrite_system_overlay(issues)

        try:
            # 调用 LLM 重写
            new_content = llm_client.generate(
                prompt=rewrite_prompt,
                system_prompt=enhanced_system,
                temperature=min(0.85, config.generation.chapter_temperature + 0.1),
                max_tokens=4096,
                context={k: v[:1000] for k, v in knowledge_context.items() if v}
                if knowledge_context else {},
            )

            if not new_content or len(new_content) < 2000:
                logger.warning(f"重写内容过短 ({len(new_content)}字)，保留原始版本")
                return None

            # 记录重写历史
            rewrite_record = {
                "chapter_number": chapter_number,
                "original_score": original_score,
                "original_issues": issues,
                "original_content_len": len(original_content),
                "new_content_len": len(new_content),
                "rewrite_reasons": [i["reason"] for i in issues],
            }
            self.rewrite_history.append(rewrite_record)

            # 持久化重写记录到日志
            self._log_rewrite_record(rewrite_record)

            logger.info(
                f"第 {chapter_number} 章重写完成: "
                f"{len(original_content)}字 → {len(new_content)}字"
            )

            return {
                "content": new_content,
                "is_rewrite": True,
                "original_score": original_score,
                "rewrite_reasons": [i["reason"] for i in issues],
            }

        except Exception as e:
            logger.error(f"第 {chapter_number} 章重写失败: {e}", exc_info=True)
            return None

    def update_chapter_record(
        self,
        chapter_number: int,
        new_content: str,
        new_score: float,
        rewrite_info: Dict,
    ):
        """更新数据库中的章节记录"""
        try:
            records = db_client.get_all(Chapter, project_id=self.project_id)
            for record in records:
                if record.chapter_number == chapter_number:
                    record.content = new_content
                    record.word_count = len(new_content)
                    record.quality_score = new_score
                    record.quality_details = {
                        **rewrite_info,
                        "rewrite_count": len(self.rewrite_history),
                    }
                    db_client.update(record)
                    logger.info(
                        f"第 {chapter_number} 章数据库记录已更新 "
                        f"(新评分: {new_score:.2f})"
                    )
                    break
        except Exception as e:
            logger.error(f"更新重写记录失败: {e}")

    # ==================== 私有方法 ====================

    def _build_rewrite_prompt(
        self,
        chapter_number: int,
        chapter_outline: Dict,
        original_content: str,
        issues: List[Dict],
    ) -> str:
        """构建重写提示"""
        # 提取问题摘要
        issue_summary = "\n".join(
            f"- [{i.get('severity', '?')}] {i['reason']}\n  修复方向: {i.get('fix_hint', '')}"
            for i in issues
        )

        prompt = (
            f"以下是第 {chapter_number} 章的原始内容，但质量评估发现了以下问题：\n\n"
            f"【发现的问题】\n{issue_summary}\n\n"
            f"【章节大纲】\n"
            f"标题: {chapter_outline.get('title', '')}\n"
            f"概要: {chapter_outline.get('summary', '')}\n"
            f"关键事件: {', '.join(chapter_outline.get('key_events', []))}\n\n"
            f"【原始内容（需要改进的部分）】\n{original_content[:3000]}\n\n"
            f"请根据以上问题诊断，重新编写本章内容。重写要求：\n"
        )

        # 根据具体问题追加重写指令
        for issue in issues:
            dim = issue.get("dimension", "")
            if dim == "dialogue":
                prompt += (
                    "1. 大幅增加角色对话：每段至少 2 轮对话，对话占比不低于 30%\n"
                    "2. 用对话推进剧情，减少旁白叙述\n"
                    "3. 对话要有个性差异：不同角色说话方式要明显不同\n"
                )
            elif dim == "ai_traces":
                prompt += (
                    "1. 消除所有AI模板表达：禁止'瞬间''嘴角''眼中闪过'等\n"
                    "2. 用更自然、更个性化的表达替代\n"
                    "3. 句式要多样化，避免重复的时间过渡词\n"
                )
            elif dim == "style":
                prompt += (
                    "1. 减少比喻，用直接的感官描写替代\n"
                    "2. 增加幽默感和吐槽（角色内心独白要有自嘲）\n"
                    "3. 段落开头要多样化，不要总以'他'开头\n"
                )
            elif dim == "llm_quality":
                prompt += (
                    "1. 加强情节逻辑，避免不合理的转折\n"
                    "2. 角色行为要有明确动机\n"
                    "3. 战斗/冲突场景要有意外和变数\n"
                )

        prompt += (
            "\n直接输出完整的重写内容，不要任何前言或解释。"
            f"\n目标字数: {config.generation.words_per_chapter} 字左右。"
        )

        return prompt

    def _build_rewrite_system_overlay(self, issues: List[Dict]) -> str:
        """根据问题类型构建额外的系统提示"""
        overlay = (
            "\n\n【重写模式 — 特别注意】\n"
            "这是一次质量改进重写，你必须重点修正以下问题：\n"
        )

        dims = {i["dimension"] for i in issues}

        if "dialogue" in dims:
            overlay += (
                "- 对话要求：角色对话必须占全文30%以上。"
                "每个场景至少包含一轮完整的对话交流。"
                "对话要有口语感：用断句、语气词、省略，不要用书面语。"
                "不同角色的说话风格要有明显差异。\n"
            )

        if "ai_traces" in dims:
            overlay += (
                "- AI痕迹消除：绝对禁止使用'瞬间''骤然''嘴角勾起''眼中闪过'等AI模板词。"
                "时间过渡用具体场景细节替代（如'门被推开的声音打断了他的思绪'），"
                "不要用'一瞬间''下一秒'这类抽象过渡。\n"
            )

        if "style" in dims:
            overlay += (
                "- 风格改进：比喻总量控制在全章5次以内。"
                "增加幽默元素——角色的内心吐槽、不合时宜的大实话、反差行为。"
                "段落开头用环境细节、动作、对话开头，禁止连续3段以'他'开头。\n"
            )

        if "llm_quality" in dims:
            overlay += (
                "- 情节质量：每个场景都要有明确的冲突或目标。"
                "主角不能太顺利，必须有失误或意外。"
                "结尾用具体的悬念画面收束，禁止感慨式收尾。\n"
            )

        return overlay

    def _log_rewrite_record(self, record: Dict):
        """将重写记录写入日志文件"""
        import json
        from pathlib import Path

        log_dir = Path(config.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "rewrite_history.jsonl"

        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"写入重写日志失败: {e}")

    def get_rewrite_summary(self) -> Dict:
        """获取重写汇总统计"""
        if not self.rewrite_history:
            return {"total_rewrites": 0}

        return {
            "total_rewrites": len(self.rewrite_history),
            "chapters_rewritten": [r["chapter_number"] for r in self.rewrite_history],
            "avg_original_score": sum(
                r["original_score"] for r in self.rewrite_history
            ) / len(self.rewrite_history),
            "common_reasons": self._get_common_reasons(),
        }

    def _get_common_reasons(self) -> List[str]:
        """统计最常见的的重写原因"""
        from collections import Counter
        reason_counter = Counter()
        for record in self.rewrite_history:
            for reason in record.get("rewrite_reasons", []):
                reason_counter[reason] += 1
        return [f"{r} ({c}次)" for r, c in reason_counter.most_common(5)]
