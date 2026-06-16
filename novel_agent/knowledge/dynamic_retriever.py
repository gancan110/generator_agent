"""
智能检索器 - 动态权重调整

根据查询类型和上下文动态调整检索策略，提升检索效果。

核心改进:
├── 查询意图识别: 自动判断查询类型
├── 动态权重调整: 根据查询类型调整语义/关键词权重
├── 上下文感知: 基于当前章节和大纲优化检索
└── 多路召回: 融合多种检索结果
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class QueryType(Enum):
    """查询类型枚举"""
    CHARACTER = "character"      # 角色查询
    ITEM = "item"                # 物品查询
    PLOT = "plot"                # 情节查询
    WORLDVIEW = "worldview"      # 世界观查询
    SUSPENSE = "suspense"        # 悬念查询
    SCENE = "scene"              # 场景查询
    UNKNOWN = "unknown"          # 未知类型


@dataclass
class RetrievalConfig:
    """检索配置"""
    semantic_weight: float  # 语义检索权重
    bm25_weight: float     # BM25检索权重
    top_k: int             # 返回结果数
    min_similarity: float  # 最小相似度阈值
    rerank: bool           # 是否重排序


# 查询类型到检索配置的映射
QUERY_TYPE_CONFIGS = {
    QueryType.CHARACTER: RetrievalConfig(
        semantic_weight=0.8,
        bm25_weight=0.2,
        top_k=8,
        min_similarity=0.25,
        rerank=True,
    ),
    QueryType.ITEM: RetrievalConfig(
        semantic_weight=0.4,
        bm25_weight=0.6,
        top_k=6,
        min_similarity=0.3,
        rerank=True,
    ),
    QueryType.PLOT: RetrievalConfig(
        semantic_weight=0.6,
        bm25_weight=0.4,
        top_k=10,
        min_similarity=0.2,
        rerank=True,
    ),
    QueryType.WORLDVIEW: RetrievalConfig(
        semantic_weight=0.7,
        bm25_weight=0.3,
        top_k=5,
        min_similarity=0.3,
        rerank=False,
    ),
    QueryType.SUSPENSE: RetrievalConfig(
        semantic_weight=0.65,
        bm25_weight=0.35,
        top_k=5,
        min_similarity=0.25,
        rerank=True,
    ),
    QueryType.SCENE: RetrievalConfig(
        semantic_weight=0.75,
        bm25_weight=0.25,
        top_k=6,
        min_similarity=0.2,
        rerank=True,
    ),
    QueryType.UNKNOWN: RetrievalConfig(
        semantic_weight=0.7,
        bm25_weight=0.3,
        top_k=8,
        min_similarity=0.2,
        rerank=True,
    ),
}


class QueryIntentAnalyzer:
    """
    查询意图分析器
    
    分析查询文本，识别查询类型和关键实体。
    """
    
    # 角色相关关键词
    CHARACTER_KEYWORDS = {
        "主角", "反派", "配角", "师父", "弟子", "师兄", "师姐",
        "敌人", "盟友", "伙伴", "妻子", "丈夫", "父亲", "母亲",
        "族长", "掌门", "长老", "宗主", "城主", "国王",
    }
    
    # 物品相关关键词
    ITEM_KEYWORDS = {
        "法宝", "功法", "丹药", "武器", "装备", "阵法",
        "灵石", "灵药", "灵兽", "飞剑", "护甲", "符箓",
        "秘籍", "典籍", "卷轴", "地图", "钥匙", "令牌",
    }
    
    # 情节相关关键词
    PLOT_KEYWORDS = {
        "战斗", "冲突", "转折", "高潮", "伏笔", "反转",
        "阴谋", "背叛", "复仇", "成长", "突破", "危机",
        "相遇", "离别", "重逢", "决战", "冒险", "探索",
    }
    
    # 世界观相关关键词
    WORLDVIEW_KEYWORDS = {
        "世界", "势力", "宗门", "家族", "国家", "大陆",
        "修炼", "境界", "天道", "规则", "法则", "时代",
        "历史", "传说", "神话", "文明", "种族", "魔法",
    }
    
    # 悬念相关关键词
    SUSPENSE_KEYWORDS = {
        "悬念", "谜团", "秘密", "真相", "谜题", "线索",
        "伏笔", "暗示", "预兆", "阴谋", "背后", "隐藏",
    }
    
    def __init__(self):
        """初始化意图分析器"""
        self._compiled_patterns = self._compile_patterns()
    
    def _compile_patterns(self) -> Dict[QueryType, List[re.Pattern]]:
        """预编译正则表达式"""
        patterns = {
            QueryType.CHARACTER: [],
            QueryType.ITEM: [],
            QueryType.PLOT: [],
            QueryType.WORLDVIEW: [],
            QueryType.SUSPENSE: [],
        }
        
        # 角色模式
        for kw in ["的.*角色", "人物.*介绍", "角色.*信息"]:
            patterns[QueryType.CHARACTER].append(re.compile(kw))
        
        # 物品模式
        for kw in ["法宝.*介绍", "物品.*信息", "装备.*属性"]:
            patterns[QueryType.ITEM].append(re.compile(kw))
        
        return patterns
    
    def analyze(self, query: str, context: Optional[Dict] = None) -> Tuple[QueryType, Dict]:
        """
        分析查询意图
        
        Args:
            query: 查询文本
            context: 上下文信息（可选）
            
        Returns:
            (查询类型, 分析结果)
        """
        query_lower = query.lower()
        
        # 计算各类型的匹配分数
        scores = {
            QueryType.CHARACTER: 0.0,
            QueryType.ITEM: 0.0,
            QueryType.PLOT: 0.0,
            QueryType.WORLDVIEW: 0.0,
            QueryType.SUSPENSE: 0.0,
        }
        
        # 关键词匹配
        for kw in self.CHARACTER_KEYWORDS:
            if kw in query_lower:
                scores[QueryType.CHARACTER] += 1.0
        
        for kw in self.ITEM_KEYWORDS:
            if kw in query_lower:
                scores[QueryType.ITEM] += 1.0
        
        for kw in self.PLOT_KEYWORDS:
            if kw in query_lower:
                scores[QueryType.PLOT] += 1.0
        
        for kw in self.WORLDVIEW_KEYWORDS:
            if kw in query_lower:
                scores[QueryType.WORLDVIEW] += 1.0
        
        for kw in self.SUSPENSE_KEYWORDS:
            if kw in query_lower:
                scores[QueryType.SUSPENSE] += 1.0
        
        # 正则模式匹配
        for qtype, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                if pattern.search(query_lower):
                    scores[qtype] += 2.0
        
        # 上下文增强
        if context:
            scores = self._enhance_with_context(scores, context)
        
        # 选择最高分类型
        max_score = max(scores.values())
        if max_score == 0:
            query_type = QueryType.UNKNOWN
        else:
            query_type = max(scores, key=scores.get)
        
        # 构建分析结果
        analysis = {
            "query_type": query_type,
            "scores": scores,
            "confidence": max_score / (sum(scores.values()) + 1e-8),
        }
        
        return query_type, analysis
    
    def _enhance_with_context(
        self,
        scores: Dict[QueryType, float],
        context: Dict,
    ) -> Dict[QueryType, float]:
        """使用上下文增强评分"""
        # 如果上下文提到角色，增强角色查询权重
        if context.get("character_names"):
            scores[QueryType.CHARACTER] += 0.5
        
        # 如果上下文提到物品关键词，增强物品查询权重
        if any(kw in str(context) for kw in self.ITEM_KEYWORDS):
            scores[QueryType.ITEM] += 0.3
        
        # 如果是悬念章节，增强悬念查询权重
        if context.get("has_suspense"):
            scores[QueryType.SUSPENSE] += 0.5
        
        return scores


class DynamicWeightRetriever:
    """
    动态权重检索器
    
    根据查询类型动态调整语义检索和BM25检索的权重。
    """
    
    def __init__(
        self,
        vector_store=None,
        bm25_scorer=None,
        reranker=None,
    ):
        """
        初始化动态权重检索器
        
        Args:
            vector_store: 向量存储实例
            bm25_scorer: BM25评分器实例
            reranker: 重排序器实例
        """
        self.vector_store = vector_store
        self.bm25_scorer = bm25_scorer
        self.reranker = reranker
        
        self.intent_analyzer = QueryIntentAnalyzer()
        
        # 统计信息
        self._stats = {
            "total_queries": 0,
            "by_type": {qt.value: 0 for qt in QueryType},
        }
    
    def search(
        self,
        query: str,
        top_k: int = 8,
        filters: Optional[Dict] = None,
        context: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        动态权重搜索
        
        Args:
            query: 查询文本
            top_k: 返回结果数
            filters: 过滤条件
            context: 上下文信息
            
        Returns:
            搜索结果列表
        """
        # 1. 分析查询意图
        query_type, analysis = self.intent_analyzer.analyze(query, context)
        config = QUERY_TYPE_CONFIGS.get(query_type, QUERY_TYPE_CONFIGS[QueryType.UNKNOWN])
        
        # 更新统计
        self._stats["total_queries"] += 1
        self._stats["by_type"][query_type.value] += 1
        
        logger.debug(
            f"查询类型: {query_type.value}, "
            f"置信度: {analysis['confidence']:.2f}, "
            f"权重: 语义={config.semantic_weight}, BM25={config.bm25_weight}"
        )
        
        # 2. 多路召回
        results = []
        
        # 语义检索
        if self.vector_store and config.semantic_weight > 0:
            semantic_results = self._semantic_search(
                query, config.top_k * 2, filters
            )
            for r in semantic_results:
                r["_semantic_score"] = r.get("similarity", 0)
                r["_bm25_score"] = 0
                results.append(r)
        
        # BM25检索
        if self.bm25_scorer and config.bm25_weight > 0:
            bm25_results = self._bm25_search(query, config.top_k * 2)
            for r in bm25_results:
                # 检查是否已存在
                existing = next(
                    (x for x in results if x.get("content") == r.get("content")),
                    None
                )
                if existing:
                    existing["_bm25_score"] = r.get("bm25_score", 0)
                else:
                    r["_semantic_score"] = 0
                    r["_bm25_score"] = r.get("bm25_score", 0)
                    results.append(r)
        
        # 3. 分数融合
        fused_results = self._fuse_scores(
            results,
            config.semantic_weight,
            config.bm25_weight,
        )
        
        # 4. 过滤低分结果
        filtered = [
            r for r in fused_results
            if r.get("_fused_score", 0) >= config.min_similarity
        ]
        
        # 5. 排序
        filtered.sort(key=lambda x: x.get("_fused_score", 0), reverse=True)
        
        # 6. 重排序（可选）
        if config.rerank and self.reranker and len(filtered) > 0:
            filtered = self.reranker.rerank(query, filtered, top_k)
        else:
            filtered = filtered[:top_k]
        
        # 7. 格式化输出
        final_results = []
        for r in filtered:
            final_results.append({
                "content": r.get("content", ""),
                "metadata": r.get("metadata", {}),
                "similarity": r.get("_fused_score", 0),
                "semantic_score": r.get("_semantic_score", 0),
                "bm25_score": r.get("_bm25_score", 0),
                "query_type": query_type.value,
            })
        
        return final_results
    
    def _semantic_search(
        self,
        query: str,
        top_k: int,
        filters: Optional[Dict],
    ) -> List[Dict]:
        """语义检索"""
        if self.vector_store is None:
            return []
        
        try:
            return self.vector_store.search(query, top_k, filters)
        except Exception as e:
            logger.warning(f"语义检索失败: {e}")
            return []
    
    def _bm25_search(self, query: str, top_k: int) -> List[Dict]:
        """BM25检索"""
        if self.bm25_scorer is None:
            return []
        
        try:
            bm25_scores = self.bm25_scorer.score(query, top_k)
            results = []
            for idx, score in bm25_scores:
                if idx < len(self.bm25_scorer._documents):
                    doc_content = " ".join(self.bm25_scorer._documents[idx])
                    results.append({
                        "content": doc_content,
                        "bm25_score": score,
                    })
            return results
        except Exception as e:
            logger.warning(f"BM25检索失败: {e}")
            return []
    
    def _fuse_scores(
        self,
        results: List[Dict],
        semantic_weight: float,
        bm25_weight: float,
    ) -> List[Dict]:
        """融合语义分数和BM25分数"""
        if not results:
            return []
        
        # 归一化分数
        semantic_scores = [r.get("_semantic_score", 0) for r in results]
        bm25_scores = [r.get("_bm25_score", 0) for r in results]
        
        max_semantic = max(semantic_scores) if semantic_scores else 1
        max_bm25 = max(bm25_scores) if bm25_scores else 1
        
        for r in results:
            norm_semantic = r.get("_semantic_score", 0) / (max_semantic + 1e-8)
            norm_bm25 = r.get("_bm25_score", 0) / (max_bm25 + 1e-8)
            
            r["_fused_score"] = (
                semantic_weight * norm_semantic +
                bm25_weight * norm_bm25
            )
        
        return results
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "total_queries": self._stats["total_queries"],
            "by_type": self._stats["by_type"].copy(),
        }


class AdaptiveRetriever:
    """
    自适应检索器
    
    根据历史检索效果自动调整权重。
    """
    
    def __init__(self, base_retriever: DynamicWeightRetriever):
        """
        初始化自适应检索器
        
        Args:
            base_retriever: 基础检索器
        """
        self.base_retriever = base_retriever
        self._feedback_history: List[Dict] = []
        self._weight_adjustments: Dict[QueryType, float] = {
            qt: 0.0 for qt in QueryType
        }
    
    def search_with_feedback(
        self,
        query: str,
        top_k: int = 8,
        filters: Optional[Dict] = None,
        context: Optional[Dict] = None,
    ) -> Tuple[List[Dict], callable]:
        """
        带反馈机制的搜索
        
        Args:
            query: 查询文本
            top_k: 返回结果数
            filters: 过滤条件
            context: 上下文信息
            
        Returns:
            (搜索结果, 反馈函数)
        """
        # 执行搜索
        results = self.base_retriever.search(
            query, top_k, filters, context
        )
        
        # 获取当前查询类型
        query_type, _ = self.base_retriever.intent_analyzer.analyze(query, context)
        
        # 创建反馈函数
        def feedback_fn(relevant_indices: List[int], score: float):
            """反馈函数：标记相关结果并调整权重"""
            self._update_weights(query_type, relevant_indices, score)
        
        return results, feedback_fn
    
    def _update_weights(
        self,
        query_type: QueryType,
        relevant_indices: List[int],
        score: float,
    ):
        """根据反馈更新权重"""
        # 记录反馈
        self._feedback_history.append({
            "query_type": query_type,
            "relevant_indices": relevant_indices,
            "score": score,
        })
        
        # 简单的权重调整策略
        # 如果score高，保持当前权重；如果score低，微调权重
        if score < 0.5:
            # 效果不好，增加BM25权重
            self._weight_adjustments[query_type] += 0.05
            logger.debug(f"调整权重: {query_type.value} +0.05 BM25")
        elif score > 0.8:
            # 效果很好，略微增加语义权重
            self._weight_adjustments[query_type] -= 0.02
            logger.debug(f"调整权重: {query_type.value} -0.02 BM25")
    
    def get_adjusted_config(self, query_type: QueryType) -> RetrievalConfig:
        """获取调整后的配置"""
        base_config = QUERY_TYPE_CONFIGS.get(
            query_type, QUERY_TYPE_CONFIGS[QueryType.UNKNOWN]
        )
        
        adjustment = self._weight_adjustments.get(query_type, 0.0)
        
        # 调整权重
        new_semantic = max(0.1, min(0.9, base_config.semantic_weight - adjustment))
        new_bm25 = 1.0 - new_semantic
        
        return RetrievalConfig(
            semantic_weight=new_semantic,
            bm25_weight=new_bm25,
            top_k=base_config.top_k,
            min_similarity=base_config.min_similarity,
            rerank=base_config.rerank,
        )
