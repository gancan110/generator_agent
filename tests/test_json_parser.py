"""
JSON解析器单元测试
"""

import json
import pytest

from novel_agent.utils.json_parser import (
    parse_outline_json,
    extract_outermost_json,
    fix_common_json_errors,
    parse_outline_from_text,
)


class TestParseOutlineJson:
    """parse_outline_json函数测试"""

    def test_direct_json(self):
        """测试直接JSON解析"""
        data = {"chapters": [{"title": "第1章", "summary": "摘要"}]}
        raw = json.dumps(data, ensure_ascii=False)

        result = parse_outline_json(raw)
        assert result == data

    def test_markdown_code_block(self):
        """测试从markdown代码块提取"""
        data = {"chapters": [{"title": "第1章"}]}
        raw = f"这是说明\n```json\n{json.dumps(data, ensure_ascii=False)}\n```\n更多内容"

        result = parse_outline_json(raw)
        assert result == data

    def test_plain_code_block(self):
        """测试从普通代码块提取"""
        data = {"chapters": [{"title": "第1章"}]}
        raw = f"```\n{json.dumps(data, ensure_ascii=False)}\n```"

        result = parse_outline_json(raw)
        assert result == data

    def test_extract_outermost_json(self):
        """测试提取最外层JSON"""
        text = "前缀文本 {\"key\": \"value\"} 后缀文本"
        result = extract_outermost_json(text)
        assert result == '{"key": "value"}'

    def test_no_json(self):
        """测试无JSON文本"""
        text = "没有任何JSON内容"
        result = extract_outermost_json(text)
        assert result is None

    def test_fix_trailing_comma(self):
        """测试修复尾随逗号"""
        json_str = '{"key": ["item1", "item2",], "other": 123}'
        fixed = fix_common_json_errors(json_str)
        data = json.loads(fixed)
        assert data["key"] == ["item1", "item2"]

    def test_fix_comments(self):
        """测试移除注释"""
        json_str = '{"key": "value" // 这是注释\n}'
        fixed = fix_common_json_errors(json_str)
        data = json.loads(fixed)
        assert data["key"] == "value"

    def test_fallback_to_text(self):
        """测试回退到文本解析"""
        raw = "第1章 初入江湖\n这是第一章的内容摘要\n第2章 再次出发\n第二章的内容"
        result = parse_outline_json(raw)
        assert "chapters" in result
        # 可能提取到1或2个章节，取决于解析逻辑
        assert len(result["chapters"]) >= 1


class TestParseOutlineFromText:
    """parse_outline_from_text函数测试"""

    def test_chinese_numbers(self):
        """测试中文数字章节"""
        text = "第一章 初入江湖\n这是内容\n第二章 再次出发\n更多内容"
        result = parse_outline_from_text(text)
        assert len(result["chapters"]) == 2
        assert result["chapters"][0]["chapter_number"] == 1
        assert result["chapters"][1]["chapter_number"] == 2

    def test_arabic_numbers(self):
        """测试阿拉伯数字章节"""
        text = "第1章 初入江湖\n内容\n第2章 再次出发\n更多"
        result = parse_outline_from_text(text)
        assert len(result["chapters"]) == 2

    def test_no_chapters(self):
        """测试无章节文本"""
        text = "这是一段没有章节的文本"
        result = parse_outline_from_text(text)
        assert len(result["chapters"]) == 0

    def test_chapter_ordering(self):
        """测试章节排序"""
        text = "第3章 第三章\n内容\n第1章 第一章\n内容\n第2章 第二章\n内容"
        result = parse_outline_from_text(text)
        chapters = result["chapters"]
        assert chapters[0]["chapter_number"] == 1
        assert chapters[1]["chapter_number"] == 2
        assert chapters[2]["chapter_number"] == 3

    def test_complex_outline(self):
        """测试复杂大纲"""
        text = """第1章 觉醒
        主角在偶然间觉醒了异能，开始了他的旅程。

        第2章 初遇
        在逃亡路上，主角遇到了第一个伙伴，两人决定结伴同行。

        第3章 危机
        他们遭遇了强大的敌人，不得不四散逃命。
        """
        result = parse_outline_from_text(text)
        assert len(result["chapters"]) == 3
        assert result["chapters"][0]["title"] == "觉醒"
