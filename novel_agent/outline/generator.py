"""
大纲生成器

基于知识库和用户需求，分阶段生成小说大纲。
支持初始大纲（3-5章）和后续动态更新。
"""

import json
import re
import logging
from typing import Dict, Optional, List, TYPE_CHECKING

from novel_agent.utils.llm_client import llm_client
from novel_agent.database.mysql_client import db_client
from novel_agent.database.models import Outline
from novel_agent.config import config

if TYPE_CHECKING:
    from novel_agent.skills.context import SkillContext

logger = logging.getLogger(__name__)


class OutlineGenerator:
    """
    小说大纲生成器

    基于知识库中的世界观、人物设定、写作技巧等信息，
    生成结构化的小说大纲。支持根据 Skill 定制大纲规则。
    """

    def __init__(self, project_id: int, genre: str, theme: str, skill_context: Optional["SkillContext"] = None):
        """
        Args:
            project_id: 项目 ID
            genre: 小说题材
            theme: 小说主题
            skill_context: Skill 上下文（可选）
        """
        self.project_id = project_id
        self.genre = genre
        self.theme = theme
        self.skill = skill_context

    def generate_initial_outline(self, knowledge_context: Dict[str, str]) -> Dict:
        """
        生成初始大纲（前3-5章）

        Args:
            knowledge_context: 知识上下文 {类别: 内容}

        Returns:
            大纲字典，包含章节概要和悬念点
        """
        logger.info("正在生成初始大纲（前3-5章）...")

        # 构建上下文
        context = {
            "小说类型": self.genre,
            "小说主题": self.theme,
        }
        for key, value in knowledge_context.items():
            if value:
                context[key] = value[:2000]  # 限制上下文长度

        # 构建 system_prompt（根据 Skill 定制规则）
        system_prompt = self._build_outline_system_prompt()

        prompt = (
            f"请为一部 [{self.genre}] 类型的小说生成前5章的详细大纲。\n"
            f"主题：{self.theme}\n\n"
            f"【结构要求】\n"
            f"1. 每章大纲包含：章节标题、核心剧情、出场人物、悬念/伏笔、爽点设置\n"
            f"2. 前3章完成'黄金三章'：建立人设、展示金手指（但限制能力范围）、制造第一个高潮\n"
            f"3. 每章结尾必须有具体的悬念钩子（一个事件或画面，不是感慨句）\n"
            f"4. 节奏紧凑，不要拖沓\n"
            f"5. 【重要】主角名字必须独特，避免使用'林默'、'萧炎'、'叶辰'等烂大街的名字，选择3个字左右的有特色名字，如'陆铮'、'苏九'、'顾言'等\n\n"
            f"请以JSON格式输出，结构如下：\n"
            f'{{"chapters": [{{"chapter_number": 1, "title": "章节标题", '
            f'"summary": "剧情概要(100字内)", "key_events": ["事件1"], '
            f'"characters": ["角色1(主角名字放首位)"], "suspense": ["悬念1"], '
            f'"hook": "章末钩子(具体事件，非感慨句)", '
            f'"power_change": "本章主角实力变化(无/小提升/大提升)", '
            f'"protagonist_setback": "主角是否受挫(是/否)"}}]}}\n\n'
            f"再次强调：只输出JSON，不要任何额外文字。"
        )

        raw_result = llm_client.generate_structured(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            max_tokens=4096,
            context=context,
        )

        # 解析结果
        outline_data = self._parse_outline(raw_result)

        # 存储到数据库
        outline_record = Outline(
            project_id=self.project_id,
            phase="initial",
            chapter_start=1,
            chapter_end=len(outline_data.get("chapters", [])),
            content=raw_result,
            summary=self._generate_summary(outline_data),
            key_events=self._extract_all_events(outline_data),
            suspense_points=self._extract_all_suspense(outline_data),
        )
        db_client.add(outline_record)

        logger.info(f"初始大纲已生成，共 {len(outline_data.get('chapters', []))} 章")
        return outline_data

    def _build_outline_system_prompt(self) -> str:
        """
        构建大纲生成的 system prompt。

        根据 Skill 定制力量进阶规则和题材特有规则。
        """
        base_prompt = (
            "你是一位资深的网文策划师，擅长设计紧凑、吸引人的小说大纲。"
            "你深知'先抑后扬'的道理——主角必须经历真正的困境才能让胜利有分量。\n\n"
        )

        # 力量进阶规则（根据 Skill 定制）
        power_rules = None
        suspense_rules = None
        genre_rules = None

        if self.skill:
            power_rules = self.skill.get_power_progression_rules()
            suspense_rules = self.skill.outline_overlay.get("suspense_rules")
            genre_rules = self.skill.get_genre_specific_outline_rules()

        # 力量进阶铁律
        if power_rules:
            rules_text = "\n".join(f"{i+1}. {r}" for i, r in enumerate(power_rules))
            base_prompt += f"【力量进阶铁律 — 必须严格遵守】\n{rules_text}\n\n"
        else:
            # 默认规则
            base_prompt += (
                "【升级节奏铁律 — 必须严格遵守】\n"
                "1. 金手指初始只能展示1-2个基础功能，不能一章内展示全部能力\n"
                "2. 主角每次使用能力必须付出明确代价（受伤/消耗/失误）\n"
                "3. 前5章主角最多提升1个小境界，不允许跳级\n"
                "4. 战斗必须有至少一次挫折或意外，不允许完美碾压\n"
                "5. 不允许在前5章出现吸取他人修为等过快升级手段\n\n"
            )

        # 悬念衔接规则
        if suspense_rules:
            rules_text = "\n".join(f"{i+1}. {r}" for i, r in enumerate(suspense_rules))
            base_prompt += f"【悬念衔接规则】\n{rules_text}\n\n"
        else:
            base_prompt += (
                "【悬念衔接规则】\n"
                "1. 每章开头必须处理上一章结尾的钩子\n"
                "2. 不允许跳过读者期待的对决或事件\n"
                "3. 新悬念引入速度不超过每章2个\n\n"
            )

        # 题材特有规则
        if genre_rules:
            rules_text = "\n".join(f"- {r}" for r in genre_rules)
            base_prompt += f"【题材特有规则】\n{rules_text}\n\n"

        base_prompt += "重要：你的输出必须是纯JSON，不要包含任何解释、前言或markdown标记。"

        return base_prompt

    def _parse_outline(self, raw_text: str) -> Dict:
        """
        解析 LLM 生成的大纲文本
        
        多重解析策略：
        1. 直接 JSON 解析
        2. 提取 ```json ... ``` 代码块
        3. 查找最外层 { ... } 匹配
        4. 正则修复常见 JSON 错误后重试
        5. 从纯文本中提取章节信息（最终回退）
        """
        text = raw_text.strip()
        
        # 策略1: 直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 策略2: 提取 markdown 代码块
        if "```json" in text:
            try:
                json_block = text.split("```json")[1].split("```")[0].strip()
                return json.loads(json_block)
            except (IndexError, json.JSONDecodeError):
                pass
        if "```" in text:
            try:
                json_block = text.split("```")[1].split("```")[0].strip()
                return json.loads(json_block)
            except (IndexError, json.JSONDecodeError):
                pass

        # 策略3: 查找最外层 { ... } 匹配
        json_str = self._extract_outermost_json(text)
        if json_str:
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                # 策略4: 修复常见 JSON 错误后重试
                fixed = self._fix_common_json_errors(json_str)
                if fixed:
                    try:
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        pass

        # 策略5: 从纯文本中提取章节信息
        logger.warning("大纲 JSON 解析失败，尝试从纯文本提取章节信息")
        fallback = self._parse_outline_from_text(text)
        if fallback.get("chapters"):
            logger.info(f"从纯文本成功提取 {len(fallback['chapters'])} 章大纲")
            return fallback

        logger.error("大纲解析完全失败，使用默认大纲")
        return {"chapters": [{"title": "大纲解析失败", "summary": raw_text[:500]}]}

    def _extract_outermost_json(self, text: str) -> Optional[str]:
        """从文本中提取最外层的 JSON 对象 {...}"""
        start = text.find('{')
        if start == -1:
            return None
        
        # 从后向前找最后一个 }
        end = text.rfind('}')
        if end == -1 or end <= start:
            return None
        
        candidate = text[start:end + 1]
        return candidate

    def _fix_common_json_errors(self, json_str: str) -> Optional[str]:
        """修复常见的 JSON 格式错误"""
        fixed = json_str
        # 移除末尾多余的逗号 (在 ] 或 } 前的逗号)
        fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
        # 将单引号替换为双引号（简单处理）
        # 注意：这个替换不够安全，只对简单情况有效
        # 移除注释行 (// 开头)
        fixed = re.sub(r'//.*?\n', '\n', fixed)
        # 尝试修复缺少引号的 key
        fixed = re.sub(r'(?<=[{,])\s*(\w+)\s*:', r' "\1":', fixed)
        return fixed

    def _parse_outline_from_text(self, text: str) -> Dict:
        """从非JSON纯文本中提取章节大纲信息"""
        chapters = []
        
        # 匹配 "第X章" 或 "第X章：标题" 等模式
        chapter_pattern = re.compile(
            r'第\s*(\d+|[一二三四五六七八九十]+)\s*章[：:．.\s]*(.{1,30})',
            re.MULTILINE
        )
        matches = list(chapter_pattern.finditer(text))
        
        if not matches:
            return {"chapters": []}
        
        for i, match in enumerate(matches):
            # 转换中文数字
            num_str = match.group(1)
            chapter_num = self._cn_to_num(num_str)
            
            title = match.group(2).strip().rstrip('。，,.')
            
            # 提取该章节到下一章节之间的文本作为 summary
            start_pos = match.end()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chapter_text = text[start_pos:end_pos].strip()
            
            # 取前200字作为 summary
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
        
        return {"chapters": chapters}

    def _cn_to_num(self, cn_str: str) -> int:
        """中文数字转阿拉伯数字"""
        cn_map = {
            '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
            '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        }
        try:
            return int(cn_str)
        except ValueError:
            # 简单处理中文数字（支持一到十九）
            total = 0
            if '十' in cn_str:
                parts = cn_str.split('十')
                tens = cn_map.get(parts[0], 1) if parts[0] else 1
                total = tens * 10
                if len(parts) > 1 and parts[1]:
                    total += cn_map.get(parts[1], 0)
            else:
                total = cn_map.get(cn_str, 1)
            return total

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
            if ch.get("hook"):
                suspense.append(ch["hook"])
        return suspense
