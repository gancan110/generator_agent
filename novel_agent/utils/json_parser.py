"""
JSON 解析工具模块

提供公共的 JSON 解析功能，供 OutlineGenerator 和 OutlineUpdater 共用。
支持多重解析策略：直接解析、代码块提取、JSON修复、纯文本提取。
"""

import re
import json
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def parse_outline_json(raw_text: str) -> Dict:
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
    for marker in ["```json", "```"]:
        if marker in text:
            try:
                block = text.split(marker, 1)[1].split("```")[0].strip()
                return json.loads(block)
            except (IndexError, json.JSONDecodeError):
                pass

    # 策略3: 查找最外层 { ... } 匹配
    json_str = extract_outermost_json(text)
    if json_str:
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # 策略4: 修复常见 JSON 错误后重试
            fixed = fix_common_json_errors(json_str)
            if fixed:
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    pass

    # 策略5: 从纯文本中提取章节信息
    logger.warning("大纲 JSON 解析失败，尝试从纯文本提取章节信息")
    fallback = parse_outline_from_text(text)
    if fallback.get("chapters"):
        logger.info(f"从纯文本成功提取 {len(fallback['chapters'])} 章大纲")
        return fallback

    logger.error("大纲解析完全失败，使用默认大纲")
    return {"chapters": [{"title": "大纲解析失败", "summary": raw_text[:500]}]}


def extract_outermost_json(text: str) -> Optional[str]:
    """从文本中提取最外层的 JSON 对象 {...}"""
    start = text.find('{')
    if start == -1:
        return None
    
    # 从后向前找最后一个 }
    end = text.rfind('}')
    if end == -1 or end <= start:
        return None
    
    return text[start:end + 1]


def fix_common_json_errors(json_str: str) -> Optional[str]:
    """修复常见的 JSON 格式错误"""
    fixed = json_str
    # 移除末尾多余的逗号 (在 ] 或 } 前的逗号)
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
    # 移除注释行 (// 开头)
    fixed = re.sub(r'//.*?\n', '\n', fixed)
    # 尝试修复缺少引号的 key
    fixed = re.sub(r'(?<=[{,])\s*(\w+)\s*:', r' "\1":', fixed)
    return fixed


def parse_outline_from_text(text: str) -> Dict:
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

    # 按章节号排序
    chapters.sort(key=lambda c: c["chapter_number"])
    return {"chapters": chapters}
