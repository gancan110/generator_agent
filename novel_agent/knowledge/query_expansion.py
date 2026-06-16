"""
查询扩展模块

使用多种技术扩展查询，提升检索召回率。

核心技术:
├── HyDE (Hypothetical Document Embeddings): 生成假设文档
├── Query Expansion: 同义词/相关词扩展
├── Multi-query: 多角度查询生成
└── Step-back Query: 抽象层次提升
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExpansionConfig:
    """查询扩展配置"""
    hyde_enabled: bool = True
    expansion_enabled: bool = True
    multi_query_enabled: bool = True
    step_back_enabled: bool = True
    max_expanded_queries: int = 5


class HyDEExpander:
    """
    HyDE (Hypothetical Document Embeddings) 扩展器
    
    原理: 生成一个假设的文档，用该文档的向量进行检索，
    而不是用原始查询的向量。因为文档通常比查询更接近目标文档的分布。
    """
    
    def __init__(self, llm_client=None):
        """
        初始化HyDE扩展器
        
        Args:
            llm_client: LLM客户端
        """
        self.llm_client = llm_client
    
    def expand(
        self,
        query: str,
        context: Optional[Dict] = None,
    ) -> str:
        """
        生成假设文档
        
        Args:
            query: 原始查询
            context: 上下文信息
            
        Returns:
            假设文档文本
        """
        if self.llm_client is None:
            return query
        
        # 构建提示
        prompt = self._build_prompt(query, context)
        
        try:
            hypothetical_doc = self.llm_client.generate(
                prompt=prompt,
                system_prompt=(
                    "你是一位小说创作专家。根据用户的查询，生成一段可能出现在小说中的内容。"
                    "这段内容应该包含与查询相关的信息，但要以叙事的方式呈现。"
                ),
                temperature=0.7,
                max_tokens=300,
            )
            
            # 限制长度
            return hypothetical_doc[:500]
            
        except Exception as e:
            logger.warning(f"HyDE生成失败: {e}")
            return query
    
    def _build_prompt(self, query: str, context: Optional[Dict]) -> str:
        """构建HyDE提示"""
        base_prompt = f"""请根据以下查询，生成一段可能出现在小说中的内容：

查询：{query}

要求：
1. 以叙事的方式呈现
2. 包含与查询相关的关键信息
3. 长度约200-300字
4. 符合小说的写作风格"""
        
        if context:
            if context.get("genre"):
                base_prompt += f"\n题材：{context['genre']}"
            if context.get("chapter_number"):
                base_prompt += f"\n当前章节：第{context['chapter_number']}章"
        
        return base_prompt


class QueryExpansion:
    """
    查询扩展器
    
    使用同义词和相关词扩展查询。
    """
    
    # 预定义的相关词映射
    RELATED_WORDS = {
        "战斗": ["战斗", "交手", "对决", "激战", "厮杀", "搏斗"],
        "修炼": ["修炼", "修炼", "闭关", "突破", "晋级", "提升"],
        "阴谋": ["阴谋", "诡计", "算计", "陷阱", "圈套", "暗算"],
        "感情": ["感情", "爱情", "情愫", "心动", "倾心", "相思"],
        "危险": ["危险", "危机", "险境", "困境", "绝境", "险情"],
        "实力": ["实力", "修为", "境界", "战力", "功力", "道行"],
    }
    
    def __init__(self, llm_client=None):
        """
        初始化查询扩展器
        
        Args:
            llm_client: LLM客户端（可选）
        """
        self.llm_client = llm_client
        self._word_cache: Dict[str, List[str]] = {}
    
    def expand(
        self,
        query: str,
        max_expansions: int = 3,
        context: Optional[Dict] = None,
    ) -> List[str]:
        """
        扩展查询
        
        Args:
            query: 原始查询
            max_expansions: 最大扩展数
            context: 上下文信息
            
        Returns:
            扩展后的查询列表
        """
        expanded = [query]  # 原始查询
        
        # 1. 同义词扩展
        synonym_queries = self._expand_by_synonyms(query, max_expansions)
        expanded.extend(synonym_queries)
        
        # 2. LLM扩展（如果可用）
        if self.llm_client and len(expanded) < max_expansions + 1:
            llm_queries = self._expand_by_llm(
                query, max_expansions - len(expanded) + 1, context
            )
            expanded.extend(llm_queries)
        
        # 去重
        seen = set()
        unique_queries = []
        for q in expanded:
            if q not in seen:
                seen.add(q)
                unique_queries.append(q)
        
        return unique_queries[:max_expansions + 1]
    
    def _expand_by_synonyms(
        self,
        query: str,
        max_expansions: int,
    ) -> List[str]:
        """使用同义词扩展"""
        expansions = []
        
        for key, related in self.RELATED_WORDS.items():
            if key in query:
                for word in related:
                    if word != key:
                        new_query = query.replace(key, word)
                        if new_query != query and len(expansions) < max_expansions:
                            expansions.append(new_query)
                break
        
        return expansions
    
    def _expand_by_llm(
        self,
        query: str,
        max_expansions: int,
        context: Optional[Dict],
    ) -> List[str]:
        """使用LLM扩展"""
        if self.llm_client is None:
            return []
        
        prompt = f"""请为以下查询生成{max_expansions}个相关的查询变体：

原始查询：{query}

要求：
1. 保持查询意图不变
2. 使用不同的表达方式
3. 每个变体一行

输出格式：
变体1
变体2
变体3"""

        try:
            response = self.llm_client.generate(
                prompt=prompt,
                system_prompt="你是查询扩展专家，擅长生成多样化的查询变体。",
                temperature=0.8,
                max_tokens=200,
            )
            
            # 解析响应
            lines = [line.strip() for line in response.strip().split("\n") if line.strip()]
            return lines[:max_expansions]
            
        except Exception as e:
            logger.warning(f"LLM查询扩展失败: {e}")
            return []


class MultiQueryGenerator:
    """
    多角度查询生成器
    
    从不同角度生成多个查询，提升召回率。
    """
    
    # 角度模板
    ANGLE_TEMPLATES = [
        "关于{topic}的详细信息",
        "{topic}的相关情节",
        "{topic}的历史背景",
        "{topic}的角色信息",
        "{topic}的发展变化",
    ]
    
    def __init__(self, llm_client=None):
        """
        初始化多角度查询生成器
        
        Args:
            llm_client: LLM客户端
        """
        self.llm_client = llm_client
    
    def generate(
        self,
        query: str,
        num_queries: int = 3,
        context: Optional[Dict] = None,
    ) -> List[str]:
        """
        生成多角度查询
        
        Args:
            query: 原始查询
            num_queries: 生成查询数
            context: 上下文信息
            
        Returns:
            多角度查询列表
        """
        queries = [query]  # 原始查询
        
        if self.llm_client is None:
            # 降级：使用模板生成
            return self._generate_by_template(query, num_queries)
        
        prompt = f"""请从不同角度为以下查询生成{num_queries - 1}个相关查询：

原始查询：{query}

要求：
1. 每个查询从不同角度切入
2. 保持与原始查询的相关性
3. 每个查询一行

输出格式：
查询1
查询2
查询3"""

        try:
            response = self.llm_client.generate(
                prompt=prompt,
                system_prompt="你是多角度查询生成专家。",
                temperature=0.8,
                max_tokens=200,
            )
            
            lines = [line.strip() for line in response.strip().split("\n") if line.strip()]
            queries.extend(lines[:num_queries - 1])
            
        except Exception as e:
            logger.warning(f"多角度查询生成失败: {e}")
            queries.extend(self._generate_by_template(query, num_queries - 1))
        
        return queries[:num_queries]
    
    def _generate_by_template(self, query: str, num_queries: int) -> List[str]:
        """使用模板生成查询"""
        # 提取关键词
        keywords = self._extract_keywords(query)
        
        queries = []
        for template in self.ANGLE_TEMPLATES[:num_queries]:
            for keyword in keywords[:2]:
                new_query = template.format(topic=keyword)
                if new_query not in queries:
                    queries.append(new_query)
                    break
        
        return queries
    
    def _extract_keywords(self, query: str) -> List[str]:
        """提取关键词"""
        # 简单的关键词提取
        # 实际应用中可以使用jieba等分词工具
        words = []
        for word in ["战斗", "修炼", "角色", "物品", "情节", "世界"]:
            if word in query:
                words.append(word)
        
        if not words:
            words = [query[:4]]  # 取前4个字符
        
        return words


class StepBackQueryGenerator:
    """
    Step-back Query生成器
    
    生成更抽象层次的查询，获取更广泛的上下文。
    """
    
    def __init__(self, llm_client=None):
        """
        初始化Step-back Query生成器
        
        Args:
            llm_client: LLM客户端
        """
        self.llm_client = llm_client
    
    def generate(
        self,
        query: str,
        num_queries: int = 2,
        context: Optional[Dict] = None,
    ) -> List[str]:
        """
        生成Step-back查询
        
        Args:
            query: 原始查询
            num_queries: 生成查询数
            context: 上下文信息
            
        Returns:
            Step-back查询列表
        """
        if self.llm_client is None:
            return self._generate_by_rule(query, num_queries)
        
        prompt = f"""请为以下查询生成{num_queries}个更宏观/抽象的查询：

原始查询：{query}

要求：
1. 将查询提升到更高的抽象层次
2. 获取更广泛的背景信息
3. 每个查询一行

输出格式：
查询1
查询2"""

        try:
            response = self.llm_client.generate(
                prompt=prompt,
                system_prompt="你是查询抽象化专家。",
                temperature=0.7,
                max_tokens=150,
            )
            
            lines = [line.strip() for line in response.strip().split("\n") if line.strip()]
            return lines[:num_queries]
            
        except Exception as e:
            logger.warning(f"Step-back查询生成失败: {e}")
            return self._generate_by_rule(query, num_queries)
    
    def _generate_by_rule(self, query: str, num_queries: int) -> List[str]:
        """基于规则生成"""
        step_backs = []
        
        # 规则1: 如果包含具体章节，扩展到整体剧情
        if "第" in query and "章" in query:
            step_backs.append("整体剧情发展")
        
        # 规则2: 如果包含具体角色，扩展到角色关系
        for char in ["主角", "反派", "师父", "敌人"]:
            if char in query:
                step_backs.append(f"{char}的人物关系")
                break
        
        # 规则3: 如果包含具体物品，扩展到物品体系
        for item in ["法宝", "功法", "丹药"]:
            if item in query:
                step_backs.append(f"{item}的体系设定")
                break
        
        # 规则4: 通用的背景查询
        if len(step_backs) < num_queries:
            step_backs.append("世界观背景设定")
        
        return step_backs[:num_queries]


class QueryExpansionPipeline:
    """
    查询扩展流水线
    
    组合多种查询扩展技术，提供完整的扩展能力。
    """
    
    def __init__(
        self,
        llm_client=None,
        config: Optional[ExpansionConfig] = None,
    ):
        """
        初始化查询扩展流水线
        
        Args:
            llm_client: LLM客户端
            config: 扩展配置
        """
        self.config = config or ExpansionConfig()
        
        # 初始化各组件
        self.hyde = HyDEExpander(llm_client) if self.config.hyde_enabled else None
        self.expansion = QueryExpansion(llm_client) if self.config.expansion_enabled else None
        self.multi_query = MultiQueryGenerator(llm_client) if self.config.multi_query_enabled else None
        self.step_back = StepBackQueryGenerator(llm_client) if self.config.step_back_enabled else None
    
    def expand(
        self,
        query: str,
        context: Optional[Dict] = None,
    ) -> Dict[str, any]:
        """
        执行查询扩展
        
        Args:
            query: 原始查询
            context: 上下文信息
            
        Returns:
            扩展结果字典
        """
        result = {
            "original_query": query,
            "expanded_queries": [query],
            "hyde_query": None,
            "step_back_queries": [],
        }
        
        # 1. HyDE扩展
        if self.hyde:
            result["hyde_query"] = self.hyde.expand(query, context)
        
        # 2. 同义词/LLM扩展
        if self.expansion:
            expanded = self.expansion.expand(
                query,
                max_expansions=3,
                context=context,
            )
            result["expanded_queries"].extend(expanded[1:])  # 跳过原始查询
        
        # 3. 多角度查询
        if self.multi_query:
            multi_queries = self.multi_query.generate(
                query,
                num_queries=3,
                context=context,
            )
            result["expanded_queries"].extend(multi_queries[1:])
        
        # 4. Step-back查询
        if self.step_back:
            step_backs = self.step_back.generate(
                query,
                num_queries=2,
                context=context,
            )
            result["step_back_queries"] = step_backs
        
        # 去重
        seen = set()
        unique_queries = []
        for q in result["expanded_queries"]:
            if q not in seen:
                seen.add(q)
                unique_queries.append(q)
        result["expanded_queries"] = unique_queries[:self.config.max_expanded_queries]
        
        return result
    
    def get_search_queries(
        self,
        query: str,
        context: Optional[Dict] = None,
    ) -> List[Tuple[str, float, str]]:
        """
        获取用于搜索的查询列表
        
        Args:
            query: 原始查询
            context: 上下文信息
            
        Returns:
            [(查询, 权重, 类型), ...]
        """
        expansion_result = self.expand(query, context)
        
        queries = []
        
        # 原始查询权重最高
        queries.append((query, 1.0, "original"))
        
        # HyDE查询
        if expansion_result["hyde_query"]:
            queries.append((expansion_result["hyde_query"], 0.9, "hyde"))
        
        # 扩展查询
        for i, q in enumerate(expansion_result["expanded_queries"][1:]):
            weight = 0.8 - i * 0.1
            queries.append((q, max(0.5, weight), "expanded"))
        
        # Step-back查询
        for i, q in enumerate(expansion_result["step_back_queries"]):
            weight = 0.6 - i * 0.1
            queries.append((q, max(0.4, weight), "step_back"))
        
        return queries
