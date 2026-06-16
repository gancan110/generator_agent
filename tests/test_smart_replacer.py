"""
智能替换词引擎单元测试
"""

import pytest
from novel_agent.generation.smart_replacer import (
    ConfigurableSynonymPool,
    LLMContextualReplacer,
    SemanticSimilarityReplacer,
    SmartReplacerEngine,
    PostProcessingChain,
)


class TestConfigurableSynonymPool:
    """可配置同义词池测试"""

    def test_init_default(self):
        """测试默认初始化"""
        pool = ConfigurableSynonymPool()
        assert len(pool.synonyms) > 0
        assert "猛地" in pool.synonyms

    def test_get_synonyms(self):
        """测试获取同义词"""
        pool = ConfigurableSynonymPool()
        synonyms = pool.get_synonyms("猛地")
        assert len(synonyms) > 0
        assert "霍然" in synonyms

    def test_get_synonyms_unknown(self):
        """测试获取未知词的同义词"""
        pool = ConfigurableSynonymPool()
        synonyms = pool.get_synonyms("未知词汇")
        assert synonyms == []

    def test_add_synonym(self):
        """测试动态添加同义词"""
        pool = ConfigurableSynonymPool()
        pool.add_synonym("测试词", "测试同义词")
        assert "测试同义词" in pool.get_synonyms("测试词")

    def test_get_all_patterns(self):
        """测试获取所有模式"""
        pool = ConfigurableSynonymPool()
        patterns = pool.get_all_patterns()
        assert len(patterns) > 0


class TestLLMContextualReplacer:
    """LLM上下文替换器测试"""

    def test_init_without_client(self):
        """测试无客户端初始化"""
        replacer = LLMContextualReplacer()
        assert replacer.llm_client is None

    def test_replace_without_client(self):
        """测试无客户端时的替换"""
        replacer = LLMContextualReplacer()
        content = "猛地抬头，眼中闪过一丝惊讶。"
        result = replacer.replace_with_context(content, ["猛地"])
        assert result == content  # 应该返回原文


class TestSemanticSimilarityReplacer:
    """语义相似度替换器测试"""

    def test_init(self):
        """测试初始化"""
        replacer = SemanticSimilarityReplacer()
        assert replacer is not None

    def test_find_similar_words(self):
        """测试查找相似词"""
        replacer = SemanticSimilarityReplacer()
        similar = replacer.find_similar_words("突然", top_k=3)
        assert len(similar) > 0
        assert "骤然" in similar

    def test_find_similar_unknown(self):
        """测试查找未知词的相似词"""
        replacer = SemanticSimilarityReplacer()
        similar = replacer.find_similar_words("未知词汇")
        assert similar == []


class TestSmartReplacerEngine:
    """智能替换引擎测试"""

    def test_init(self):
        """测试初始化"""
        engine = SmartReplacerEngine()
        assert engine.synonym_pool is not None
        assert engine.llm_replacer is not None

    def test_detect_high_frequency_words(self):
        """测试高频词检测"""
        engine = SmartReplacerEngine()
        content = "猛地抬头，猛地站起，猛地转身。瞬间移动，瞬间爆发。"
        words = engine._detect_high_frequency_words(content, threshold=1)
        assert "猛地" in words
        assert "瞬间" in words

    def test_apply_rule_replace(self):
        """测试规则替换"""
        engine = SmartReplacerEngine()
        content = "猛地抬头，猛地站起。"
        new_content, count = engine._apply_rule_replace(content, "猛地")
        assert count > 0
        assert "猛地" not in new_content or new_content.count("猛地") < content.count("猛地")

    def test_smart_replace_auto(self):
        """测试自动策略替换"""
        engine = SmartReplacerEngine()
        content = "猛地抬头，猛地站起，猛地转身，猛地坐下。" * 2
        result = engine.smart_replace(content, strategy="auto")
        assert isinstance(result, str)

    def test_smart_replace_rule(self):
        """测试规则策略替换"""
        engine = SmartReplacerEngine()
        content = "猛地抬头，猛地站起，猛地转身。"
        result = engine.smart_replace(content, target_words=["猛地"], strategy="rule")
        assert isinstance(result, str)


class TestPostProcessingChain:
    """后处理链测试"""

    def test_init(self):
        """测试初始化"""
        chain = PostProcessingChain()
        assert "light" in chain.chains
        assert "standard" in chain.chains
        assert "full" in chain.chains

    def test_register_chain(self):
        """测试注册自定义链"""
        chain = PostProcessingChain()
        chain.register_chain("custom", ["rule_replace"])
        assert "custom" in chain.chains

    def test_execute_light(self):
        """测试执行轻量级链"""
        chain = PostProcessingChain()
        content = "猛地抬头，猛地站起。"
        result = chain.execute(content, chain_name="light")
        assert isinstance(result, str)

    def test_execute_standard(self):
        """测试执行标准链"""
        chain = PostProcessingChain()
        content = "猛地抬头，瞬间移动。" * 3
        result = chain.execute(content, chain_name="standard")
        assert isinstance(result, str)


class TestIntegration:
    """集成测试"""

    def test_full_pipeline(self):
        """测试完整流程"""
        engine = SmartReplacerEngine()
        content = """
        猛地抬头，眼中闪过一丝惊讶。嘴角勾起一个弧度，冷冷道："你来了。"
        瞬间，他猛地站起，握紧拳头。深吸一口气，瞳孔收缩。
        像是一头猛兽，就像是饿狼，仿佛要吞噬一切。
        """
        result = engine.smart_replace(content, strategy="auto")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_with_config_file(self):
        """测试使用配置文件"""
        import tempfile
        import json
        
        config = {
            "synonyms": {
                "test_word": ["replacement1", "replacement2", "replacement3"]
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False)
            config_path = f.name
        
        try:
            pool = ConfigurableSynonymPool(config_path)
            assert "test_word" in pool.synonyms
            assert "replacement1" in pool.get_synonyms("test_word")
        finally:
            import os
            os.unlink(config_path)
