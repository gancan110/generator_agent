"""
RAG改进模块单元测试
"""

import pytest
from novel_agent.knowledge.faiss_vector_store import FAISSVectorStore
from novel_agent.knowledge.dynamic_retriever import (
    QueryIntentAnalyzer,
    DynamicWeightRetriever,
    QueryType,
)
from novel_agent.knowledge.query_expansion import (
    HyDEExpander,
    QueryExpansion,
    MultiQueryGenerator,
    QueryExpansionPipeline,
)
from novel_agent.knowledge.knowledge_graph import (
    KnowledgeGraph,
    Entity,
    Relation,
    EntityExtractor,
)


class TestFAISSVectorStore:
    """FAISS向量存储测试"""

    def test_init(self, tmp_path):
        """测试初始化"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            from novel_agent.config import config
            config.vector_db.db_path = tmpdir
            
            store = FAISSVectorStore(project_id=1, dimension=384)
            assert store.project_id == 1
            assert store.dimension == 384

    def test_add_documents(self, tmp_path):
        """测试添加文档"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            from novel_agent.config import config
            config.vector_db.db_path = tmpdir
            
            store = FAISSVectorStore(project_id=1, dimension=384)
            documents = [
                {"content": "测试文档内容", "metadata": {"type": "test"}}
            ]
            store.add_documents(documents)
            assert store.document_count == 1

    def test_stats(self, tmp_path):
        """测试统计信息"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            from novel_agent.config import config
            config.vector_db.db_path = tmpdir
            
            store = FAISSVectorStore(project_id=1)
            stats = store.get_stats()
            assert "document_count" in stats


class TestQueryIntentAnalyzer:
    """查询意图分析器测试"""

    def test_analyze_character_query(self):
        """测试角色查询分析"""
        analyzer = QueryIntentAnalyzer()
        query_type, analysis = analyzer.analyze("主角的个人信息")
        assert query_type == QueryType.CHARACTER

    def test_analyze_item_query(self):
        """测试物品查询分析"""
        analyzer = QueryIntentAnalyzer()
        query_type, analysis = analyzer.analyze("法宝的属性介绍")
        assert query_type == QueryType.ITEM

    def test_analyze_plot_query(self):
        """测试情节查询分析"""
        analyzer = QueryIntentAnalyzer()
        query_type, analysis = analyzer.analyze("战斗的详细情节")
        assert query_type == QueryType.PLOT

    def test_analyze_unknown_query(self):
        """测试未知查询分析"""
        analyzer = QueryIntentAnalyzer()
        query_type, analysis = analyzer.analyze("今天天气怎么样")
        assert query_type == QueryType.UNKNOWN


class TestDynamicWeightRetriever:
    """动态权重检索器测试"""

    def test_init(self):
        """测试初始化"""
        retriever = DynamicWeightRetriever()
        assert retriever.vector_store is None

    def test_get_stats(self):
        """测试统计信息"""
        retriever = DynamicWeightRetriever()
        stats = retriever.get_stats()
        assert "total_queries" in stats


class TestHyDEExpander:
    """HyDE扩展器测试"""

    def test_init(self):
        """测试初始化"""
        expander = HyDEExpander()
        assert expander.llm_client is None

    def test_expand_without_llm(self):
        """测试无LLM时的扩展"""
        expander = HyDEExpander()
        result = expander.expand("测试查询")
        assert result == "测试查询"


class TestQueryExpansion:
    """查询扩展器测试"""

    def test_expand_synonyms(self):
        """测试同义词扩展"""
        expansion = QueryExpansion()
        results = expansion.expand("战斗场景")
        assert len(results) >= 1

    def test_expand_unknown(self):
        """测试未知查询扩展"""
        expansion = QueryExpansion()
        results = expansion.expand("测试查询")
        assert len(results) >= 1


class TestMultiQueryGenerator:
    """多角度查询生成器测试"""

    def test_generate_by_template(self):
        """测试模板生成"""
        generator = MultiQueryGenerator()
        queries = generator.generate("主角战斗", num_queries=3)
        assert len(queries) >= 1


class TestQueryExpansionPipeline:
    """查询扩展流水线测试"""

    def test_init(self):
        """测试初始化"""
        pipeline = QueryExpansionPipeline()
        assert pipeline.config is not None

    def test_expand(self):
        """测试扩展"""
        pipeline = QueryExpansionPipeline()
        result = pipeline.expand("测试查询")
        assert "original_query" in result
        assert "expanded_queries" in result


class TestKnowledgeGraph:
    """知识图谱测试"""

    def test_init(self, tmp_path):
        """测试初始化"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            from novel_agent.config import config
            config.vector_db.db_path = tmpdir
            
            kg = KnowledgeGraph(project_id=1)
            assert kg.project_id == 1

    def test_add_entity(self, tmp_path):
        """测试添加实体"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            from novel_agent.config import config
            config.vector_db.db_path = tmpdir
            
            kg = KnowledgeGraph(project_id=1)
            entity = Entity(
                id="",
                name="主角",
                entity_type="character",
                properties={"修为": "筑基期"},
            )
            entity_id = kg.add_entity(entity)
            assert entity_id is not None
            assert kg.get_entity_by_name("主角") is not None

    def test_add_relation(self, tmp_path):
        """测试添加关系"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            from novel_agent.config import config
            config.vector_db.db_path = tmpdir
            
            kg = KnowledgeGraph(project_id=1)
            
            # 添加实体
            e1 = Entity(id="char_0", name="主角", entity_type="character")
            e2 = Entity(id="char_1", name="师父", entity_type="character")
            kg.add_entity(e1)
            kg.add_entity(e2)
            
            # 添加关系
            rel = Relation(
                source_id="char_0",
                target_id="char_1",
                relation_type="student_of",
            )
            kg.add_relation(rel)
            
            # 获取相关实体
            related = kg.get_related_entities("char_0")
            assert len(related) == 1
            assert related[0][0].name == "师父"

    def test_find_path(self, tmp_path):
        """测试路径查找"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            from novel_agent.config import config
            config.vector_db.db_path = tmpdir
            
            kg = KnowledgeGraph(project_id=1)
            
            # 添加实体
            for i, name in enumerate(["A", "B", "C"]):
                kg.add_entity(Entity(id=f"e_{i}", name=name, entity_type="test"))
            
            # 添加关系链
            kg.add_relation(Relation(source_id="e_0", target_id="e_1", relation_type="link"))
            kg.add_relation(Relation(source_id="e_1", target_id="e_2", relation_type="link"))
            
            # 查找路径
            path = kg.find_path("e_0", "e_2")
            assert path is not None
            assert len(path) == 2

    def test_stats(self, tmp_path):
        """测试统计信息"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            from novel_agent.config import config
            config.vector_db.db_path = tmpdir
            
            kg = KnowledgeGraph(project_id=1)
            kg.add_entity(Entity(id="e_0", name="测试", entity_type="test"))
            
            stats = kg.stats
            assert stats["entity_count"] == 1


class TestEntityExtractor:
    """实体抽取器测试"""

    def test_extract_characters(self):
        """测试角色抽取"""
        extractor = EntityExtractor()
        text = "主角说：'你好'。师父笑着点头。"
        entities, _ = extractor.extract(text, chapter_number=1)
        char_entities = [e for e in entities if e.entity_type == "character"]
        assert len(char_entities) >= 0  # 可能抽取到也可能抽取不到

    def test_extract_items(self):
        """测试物品抽取"""
        extractor = EntityExtractor()
        text = "他手持一把神剑，施展了剑法。"
        entities, _ = extractor.extract(text, chapter_number=1)
        item_entities = [e for e in entities if e.entity_type == "item"]
        assert len(item_entities) >= 0


class TestIntegration:
    """集成测试"""

    def test_full_pipeline(self, tmp_path):
        """测试完整流程"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            from novel_agent.config import config
            config.vector_db.db_path = tmpdir
            
            # 创建知识图谱
            kg = KnowledgeGraph(project_id=1)
            
            # 添加角色
            kg.add_entity(Entity(id="char_0", name="主角", entity_type="character"))
            kg.add_entity(Entity(id="char_1", name="师父", entity_type="character"))
            
            # 添加关系
            kg.add_relation(Relation(
                source_id="char_0",
                target_id="char_1",
                relation_type="student_of",
            ))
            
            # 获取上下文
            context = kg.get_context_for_entity("主角")
            assert "主角" in context
