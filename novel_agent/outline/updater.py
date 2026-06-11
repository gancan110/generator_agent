"""
大纲动态更新器

根据已生成的章节内容、知识库更新和悬念状态，
动态调整和生成后续章节的大纲。
"""

import json
import re
import logging
from typing import Dict, List, Optional

from novel_agent.utils.llm_client import llm_client
from novel_agent.database.mysql_client import db_client
from novel_agent.database.models import Outline, Chapter, SuspenseManager
from novel_agent.config import config

logger = logging.getLogger(__name__)


class OutlineUpdater:
    """
    大纲动态更新器

    根据当前创作进度和状态，动态生成后续大纲。
    """

    def __init__(self, project_id: int):
        self.project_id = project_id

    def update_outline(
        self,
        current_chapter: int,
        knowledge_context: Dict[str, str],
        pending_suspense: List[Dict] = None,
        recent_chapters_summary: str = "",
    ) -> Dict:
        """
        基于当前进度生成后续大纲

        Args:
            current_chapter: 当前已完成章节号
            knowledge_context: 知识库上下文
            pending_suspense: 未解决的悬念列表
            recent_chapters_summary: 最近章节的摘要

        Returns:
            新的大纲字典
        """
        logger.info(f"正在更新大纲（从第 {current_chapter + 1} 章开始）...")

        # 构建悬念上下文
        suspense_text = ""
        if pending_suspense:
            suspense_items = [
                f"- [{s.get('level', 'B')}] {s.get('title', '')}: {s.get('description', '')[:100]}"
                for s in pending_suspense
            ]
            suspense_text = "\n".join(suspense_items)

        context = {
            "当前进度": f"已完成 {current_chapter} 章",
            "最近章节摘要": recent_chapters_summary[:2000],
            "未解决悬念": suspense_text or "暂无",
        }
        for key, value in knowledge_context.items():
            if value:
                context[key] = value[:1500]

        prompt = (
            f"基于当前小说进度（已完成{current_chapter}章），"
            f"请生成后续5章的详细大纲。\n\n"
            f"要求：\n"
            f"1. 确保与前文衔接自然\n"
            f"2. 推进主线剧情发展\n"
            f"3. 合理安排悬念的引入和解决\n"
            f"4. 保持爽点节奏（每2-3章一个小高潮）\n"
            f"5. 如有未解决的悬念，适时推进或解决\n\n"
            f"【升级节奏铁律】\n"
            f"1. 主角每次使用能力必须付出明确代价\n"
            f"2. 战斗必须有至少一次挫折或意外\n"
            f"3. 每章开头必须处理上一章结尾的钩子\n"
            f"4. 每章结尾必须有具体的悬念画面（不是感慨句）\n\n"
            f"请以JSON格式输出，结构如下：\n"
            f'{{"chapters": [{{"chapter_number": {current_chapter + 1}, '
            f'"title": "章节标题", "summary": "剧情概要(100字内)", '
            f'"key_events": ["事件1"], "characters": ["角色1"], '
            f'"suspense": ["悬念1"], "hook": "章末钩子"}}]}}\n\n'
            f"再次强调：只输出JSON，不要任何额外文字。"
        )

        raw_result = llm_client.generate_structured(
            prompt=prompt,
            system_prompt=(
                "你是一位资深的网文策划师，正在为一部连载小说规划后续剧情。"
                "请确保与前文衔接，并以JSON格式输出。"
                "重要：只输出纯JSON，不要包含任何解释、前言或markdown标记。"
            ),
            temperature=0.2,
            max_tokens=4096,
            context=context,
        )

        outline_data = self._parse_outline(raw_result)

        # 存储到数据库
        chapter_count = len(outline_data.get("chapters", []))
        outline_record = Outline(
            project_id=self.project_id,
            phase="update",
            chapter_start=current_chapter + 1,
            chapter_end=current_chapter + chapter_count,
            content=raw_result,
            summary=self._generate_summary(outline_data),
            key_events=self._extract_all_events(outline_data),
            suspense_points=self._extract_all_suspense(outline_data),
            version=self._get_next_version(),
        )
        db_client.add(outline_record)

        logger.info(f"大纲已更新，覆盖第 {current_chapter + 1}-{current_chapter + chapter_count} 章")
        return outline_data

    def _parse_outline(self, raw_text: str) -> Dict:
        """
        解析 LLM 生成的大纲文本（增强版，与 OutlineGenerator 共用策略）
        """
        text = raw_text.strip()

        # 策略1: 直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 策略2: 提取 markdown 代码块
        for marker in ["```json", "```"]:
            if marker in text:
                try:
                    block = text.split(marker, 1)[1].split("```")[0].strip()
                    return json.loads(block)
                except (IndexError, json.JSONDecodeError):
                    pass

        # 策略3: 查找最外层 { ... }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # 修复尾随逗号
                fixed = re.sub(r',\s*([}\]])', r'\1', candidate)
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    pass

        # 策略4: 从纯文本提取章节信息
        logger.warning("大纲 JSON 解析失败，尝试从纯文本提取")
        return self._parse_outline_from_text(text)

    def _parse_outline_from_text(self, text: str) -> Dict:
        """从非JSON文本中提取章节大纲"""
        chapters = []
        chapter_pattern = re.compile(
            r'第\s*(\d+|[一二三四五六七八九十]+)\s*章[：:．.\s]*(.{1,30})',
            re.MULTILINE
        )
        matches = list(chapter_pattern.finditer(text))

        cn_map = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}

        for i, match in enumerate(matches):
            num_str = match.group(1)
            try:
                chapter_num = int(num_str)
            except ValueError:
                chapter_num = cn_map.get(num_str, i + 1)

            title = match.group(2).strip().rstrip('。，,.')
            start_pos = match.end()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chapter_text = text[start_pos:end_pos].strip()
            summary = chapter_text[:200].replace('\n', ' ').strip()

            chapters.append({
                "chapter_number": chapter_num,
                "title": title or f"第{chapter_num}章",
                "summary": summary,
                "key_events": [],
                "characters": [],
                "suspense": [],
                "hook": "",
                "power_change": "无",
                "protagonist_setback": "是",
            })

        if not chapters:
            logger.error("无法从文本提取任何章节信息")
            return {"chapters": []}

        logger.info(f"从纯文本提取了 {len(chapters)} 章大纲")
        return {"chapters": chapters}

    def _generate_summary(self, outline_data: Dict) -> str:
        """生成大纲摘要"""
        chapters = outline_data.get("chapters", [])
        summaries = [
            f"第{ch.get('chapter_number', i+1)}章: {ch.get('summary', '')[:100]}"
            for i, ch in enumerate(chapters)
        ]
        return "\n".join(summaries)

    def _extract_all_events(self, outline_data: Dict) -> List[str]:
        """提取所有关键事件"""
        events = []
        for ch in outline_data.get("chapters", []):
            events.extend(ch.get("key_events", []))
        return events

    def _extract_all_suspense(self, outline_data: Dict) -> List[str]:
        """提取所有悬念点"""
        suspense = []
        for ch in outline_data.get("chapters", []):
            suspense.extend(ch.get("suspense", []))
        return suspense

    def _get_next_version(self) -> int:
        """获取下一个大纲版本号"""
        records = db_client.get_all(Outline, project_id=self.project_id)
        if not records:
            return 1
        return max(r.version or 0 for r in records) + 1
