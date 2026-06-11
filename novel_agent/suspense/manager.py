"""
悬念管理器

实现悬念的完整生命周期管理：记录 → 追踪 → 回收。
每个大纲或章节生成的悬念都会被记录并追踪到解决。
"""

import json
import re
import logging
from typing import Dict, List, Optional

from novel_agent.database.mysql_client import db_client
from novel_agent.database.models import (
    SuspenseManager as SuspenseRecord,
    SuspenseLevelEnum,
    SuspenseStatusEnum,
)
from novel_agent.utils.llm_client import llm_client

logger = logging.getLogger(__name__)


class SuspenseManager:
    """
    悬念管理器

    核心逻辑：记录 → 追踪 → 回收

    悬念等级：
    - S级：主线悬念（贯穿全书，如主角身世、天道阴谋）
    - A级：卷级悬念（当前地图的核心谜团）
    - B级：章级悬念（几章内解决的小谜团）
    """

    def __init__(self, project_id: int):
        self.project_id = project_id

    def add_suspense(
        self,
        title: str,
        description: str,
        level: str = "B",
        introduced_chapter: int = 1,
        expected_resolve_chapter: int = None,
        related_characters: List[str] = None,
        related_items: List[str] = None,
    ) -> SuspenseRecord:
        """
        记录新悬念

        Args:
            title: 悬念标题
            description: 悬念描述
            level: 悬念等级（S/A/B）
            introduced_chapter: 引入章节
            expected_resolve_chapter: 预计解决章节
            related_characters: 相关角色
            related_items: 相关物品

        Returns:
            创建的悬念记录
        """
        # 容错：将非法等级映射回 B
        try:
            level_enum = SuspenseLevelEnum(level.upper())
        except ValueError:
            logger.warning(f"Unknown suspense level '{level}', fallback to B")
            level_enum = SuspenseLevelEnum.B
            level = "B"

        # 根据等级设置默认解决期限
        if expected_resolve_chapter is None:
            if level == "S":
                expected_resolve_chapter = introduced_chapter + 100  # S级：100章内
            elif level == "A":
                expected_resolve_chapter = introduced_chapter + 30   # A级：30章内
            else:
                expected_resolve_chapter = introduced_chapter + 5    # B级：5章内

        record = SuspenseRecord(
            project_id=self.project_id,
            level=level_enum,
            title=title,
            description=description,
            introduced_chapter=introduced_chapter,
            expected_resolve_chapter=expected_resolve_chapter,
            status=SuspenseStatusEnum.ACTIVE,
            related_characters=related_characters or [],
            related_items=related_items or [],
            hints_planted=[],
        )
        record_id = db_client.add(record)
        logger.info(f"新悬念已记录: [{level}] {title} (第{introduced_chapter}章)")
        return db_client.get_by_id(SuspenseRecord, record_id)

    def resolve_suspense(
        self,
        suspense_id: int,
        resolution: str,
        resolved_chapter: int,
    ):
        """
        解决悬念（回收）

        Args:
            suspense_id: 悬念 ID
            resolution: 解决方式描述
            resolved_chapter: 实际解决章节
        """
        record = db_client.get_by_id(SuspenseRecord, suspense_id)
        if not record:
            logger.warning(f"悬念不存在: ID={suspense_id}")
            return

        record.status = SuspenseStatusEnum.RESOLVED
        record.resolution = resolution
        record.actual_resolve_chapter = resolved_chapter
        db_client.update(record)
        logger.info(f"悬念已解决: {record.title} (第{resolved_chapter}章)")

    def add_hint(self, suspense_id: int, hint: str, chapter: int):
        """
        为悬念添加线索

        Args:
            suspense_id: 悬念 ID
            hint: 线索描述
            chapter: 线索出现的章节
        """
        record = db_client.get_by_id(SuspenseRecord, suspense_id)
        if not record:
            return

        hints = record.hints_planted or []
        hints.append({"hint": hint, "chapter": chapter})
        record.hints_planted = hints
        db_client.update(record)

    def process_chapter_suspense(
        self,
        chapter_number: int,
        chapter_content: str,
        new_suspense: List[str] = None,
    ) -> Dict:
        """
        处理章节中的悬念

        1. 记录章节中产生的新悬念
        2. 检查是否有悬念被解决
        3. 检查超期未解决的悬念

        Args:
            chapter_number: 章节号
            chapter_content: 章节正文
            new_suspense: 大纲中预设的新悬念列表
            
        Returns:
            处理结果 {new_suspense_titles, resolved_suspense_ids, overdue_count}
        """
        result = {
            "new_suspense_titles": [],
            "resolved_suspense_ids": [],
            "overdue_count": 0,
        }
        
        # 1. 记录预设悬念
        if new_suspense:
            for suspense_text in new_suspense:
                record = self.add_suspense(
                    title=suspense_text[:50],
                    description=suspense_text,
                    level="B",
                    introduced_chapter=chapter_number,
                )
                if record:
                    result["new_suspense_titles"].append(suspense_text[:50])

        # 2. 通过 LLM 检测章节中的新悬念和已解决的悬念
        detect_result = self._detect_suspense_changes(chapter_number, chapter_content)
        if detect_result:
            result["new_suspense_titles"].extend(detect_result.get("new_titles", []))
            result["resolved_suspense_ids"].extend(detect_result.get("resolved_ids", []))

        # 3. 检查超期悬念
        overdue = self._check_overdue_suspense(chapter_number)
        result["overdue_count"] = overdue
        
        return result

    def _detect_suspense_changes(self, chapter_number: int, content: str) -> Dict:
        """通过 LLM 检测悬念变化
        
        Returns:
            {new_titles: [...], resolved_ids: [...]}
        """
        detect_result = {"new_titles": [], "resolved_ids": []}
        
        active_suspense = self.get_pending_suspense()
        if not active_suspense:
            active_text = "暂无活跃悬念"
        else:
            active_text = "\n".join(
                f"- [ID:{s['id']}][{s['level']}] {s['title']}"
                for s in active_suspense
            )

        prompt = (
            f"分析以下小说章节，完成两项任务：\n\n"
            f"1. 识别章节中产生的新悬念（伏笔/谜题/未解答的问题）\n"
            f"2. 判断是否有以下活跃悬念在本章被解决或部分揭示\n\n"
            f"活跃悬念列表：\n{active_text}\n\n"
            f"章节内容（前2000字）：\n{content[:2000]}\n\n"
            f"请以JSON格式输出：\n"
            f'{{"new_suspense": [{{"title": "悬念标题", "description": "描述", '
            f'"level": "B"}}], '
            f'"resolved_suspense": [{{"id": 悬念ID, "resolution": "解决方式"}}]}}'
        )

        try:
            result = llm_client.generate_structured(
                prompt=prompt,
                system_prompt="你是一位精确的悬念分析师。只输出纯JSON，不要任何额外文字。",
                temperature=0.1,
                max_tokens=2048,
            )

            data = self._parse_suspense_json(result)
            if data is None:
                logger.warning(f"悬念JSON解析失败，原始内容: {result[:200]}")
                return detect_result

            # 记录新悬念（单条容错）
            for s in data.get("new_suspense", []):
                try:
                    title = s.get("title", "")
                    self.add_suspense(
                        title=title,
                        description=s.get("description", ""),
                        level=s.get("level", "B"),
                        introduced_chapter=chapter_number,
                    )
                    detect_result["new_titles"].append(title)
                except Exception as e:
                    logger.warning(f"单条悬念记录失败: {e}, 数据: {s}")

            # 解决悬念（单条容错 + null防御）
            for r in data.get("resolved_suspense", []):
                try:
                    suspense_id = r.get("id", 0)
                    if suspense_id is None or suspense_id == 0:
                        continue
                    self.resolve_suspense(
                        suspense_id=int(suspense_id),
                        resolution=r.get("resolution", ""),
                        resolved_chapter=chapter_number,
                    )
                    detect_result["resolved_ids"].append(int(suspense_id))
                except Exception as e:
                    logger.warning(f"单条悬念解决失败: {e}, 数据: {r}")

        except Exception as e:
            logger.warning(f"悬念检测失败: {e}")
        
        return detect_result

    def _parse_suspense_json(self, raw_text: str) -> Optional[Dict]:
        """
        鲁棒的悬念JSON解析
        
        多重策略：直接解析 → 代码块提取 → 最外层{}匹配 → 修复常见错误 → 截断修复
        """
        text = raw_text.strip()
        
        # 预处理：去除BOM
        if text.startswith('\ufeff'):
            text = text[1:]
        
        # 策略1: 直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # 策略2: 提取 markdown 代码块
        for marker in ["```json", "```JSON", "```"]:
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
                # 策略4: 修复常见错误后重试
                fixed = self._fix_json_errors(candidate)
                if fixed:
                    try:
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        pass
        
        # 策略5: 尝试修复截断的JSON
        repaired = self._repair_truncated_json(text)
        if repaired:
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass
        
        return None

    def _fix_json_errors(self, json_str: str) -> Optional[str]:
        """修复常见的JSON格式错误"""
        fixed = json_str
        fixed = re.sub(r',\s*([}\]])', r'\1', fixed)  # 移除尾随逗号
        fixed = re.sub(r'//[^\n]*', '', fixed)  # 移除注释
        fixed = re.sub(r'(?<=[{,])\s*(\w+)\s*:', r' "\1":', fixed)  # 修复无引号key
        return fixed

    def _repair_truncated_json(self, text: str) -> Optional[str]:
        """
        修复被截断的JSON
        
        策略：找到最后一个完整闭合的 } 或 ]，截断并补全括号
        """
        start = text.find('{')
        if start == -1:
            return None
        
        candidate = text[start:]
        
        # 扫描括号栈，找到最后一个完整的外层闭合位置
        bracket_stack = []
        in_string = False
        escape_next = False
        last_safe_pos = -1
        
        for i, ch in enumerate(candidate):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            
            if ch in '{[':
                bracket_stack.append(ch)
            elif ch in '}]':
                if bracket_stack:
                    bracket_stack.pop()
                    if len(bracket_stack) == 0:
                        last_safe_pos = i
        
        if last_safe_pos > 0:
            return candidate[:last_safe_pos + 1]
        
        # 括号栈未清空，尝试截断到最后一个逗号并补全
        last_comma = candidate.rfind(',')
        if last_comma > 0:
            truncated = candidate[:last_comma]
            closers = []
            for bracket in reversed(bracket_stack):
                closers.append(']' if bracket == '[' else '}')
            truncated += ''.join(closers)
            try:
                json.loads(truncated)
                return truncated
            except json.JSONDecodeError:
                pass
        
        return None

    def _check_overdue_suspense(self, current_chapter: int) -> int:
        """检查超期未解决的悬念
        
        Returns:
            超期悬念数量
        """
        overdue_count = 0
        active = self.get_pending_suspense()
        for s in active:
            expected = s.get("expected_resolve_chapter", 999)
            if current_chapter > expected:
                overdue_chapters = current_chapter - expected
                overdue_count += 1
                logger.warning(
                    f"悬念超期警告: [{s['level']}] {s['title']} "
                    f"(预期第{expected}章解决，已超期{overdue_chapters}章)"
                )
        return overdue_count

    def get_pending_suspense(self) -> List[Dict]:
        """
        获取所有活跃悬念

        Returns:
            悬念字典列表
        """
        records = db_client.get_all(
            SuspenseRecord,
            project_id=self.project_id,
            status=SuspenseStatusEnum.ACTIVE,
        )
        return [
            {
                "id": r.id,
                "level": r.level.value if r.level else "B",
                "title": r.title,
                "description": r.description,
                "introduced_chapter": r.introduced_chapter,
                "expected_resolve_chapter": r.expected_resolve_chapter,
                "hints": r.hints_planted or [],
            }
            for r in records
        ]

    def generate_suspense_report(self) -> str:
        """
        生成悬念状态报告

        Returns:
            报告文本
        """
        pending = self.get_pending_suspense()
        if not pending:
            return "当前无活跃悬念。"

        report_lines = [f"=== 悬念状态报告（共 {len(pending)} 个活跃悬念） ===\n"]

        for level in ["S", "A", "B"]:
            items = [s for s in pending if s["level"] == level]
            if items:
                report_lines.append(f"\n【{level}级悬念】")
                for s in items:
                    report_lines.append(
                        f"  - {s['title']} (引入于第{s['introduced_chapter']}章, "
                        f"预计第{s['expected_resolve_chapter']}章解决)"
                    )

        return "\n".join(report_lines)
