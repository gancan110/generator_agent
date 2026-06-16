"""
重排序模块

使用交叉编码器对初步检索结果进行重排序，
提高检索精度。
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """
    交叉编码器重排序器
    
    使用 cross-encoder 模型对文档-查询对进行精确相关性评分。
    """

    def __init__(self, model_name: str = None):
        """
        Args:
            model_name: 交叉编码器模型名称
        """
        self._model_name = model_name or "cross-encoder/ms-marco-MiniLM-L-6-v2"
        self._model = None
        self._loaded = False

    def _load_model(self):
        """延迟加载模型"""
        if self._loaded:
            return
        
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self._model_name)
            self._loaded = True
            logger.info(f"交叉编码器模型已加载: {self._model_name}")
        except ImportError:
            logger.warning("sentence_transformers 未安装，重排序功能不可用")
        except Exception as e:
            logger.warning(f"交叉编码器模型加载失败: {e}")

    def rerank(
        self,
        query: str,
        documents: List[Dict],
        top_k: int = 5,
    ) -> List[Dict]:
        """
        对检索结果进行重排序
        
        Args:
            query: 查询文本
            documents: 初步检索结果列表
            top_k: 返回前 k 个结果
            
        Returns:
            重排序后的结果列表
        """
        if not documents:
            return []

        self._load_model()

        if self._model is None:
            # 模型不可用，返回原始顺序
            logger.debug("交叉编码器不可用，返回原始顺序")
            return documents[:top_k]

        # 构建查询-文档对
        pairs = [(query, doc.get("content", "")) for doc in documents]

        # 计算相关性分数
        try:
            scores = self._model.predict(pairs)
        except Exception as e:
            logger.error(f"重排序失败: {e}")
            return documents[:top_k]

        # 按分数排序
        scored_docs = list(zip(documents, scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        # 返回 top_k 结果
        results = []
        for doc, score in scored_docs[:top_k]:
            reranked_doc = doc.copy()
            reranked_doc["rerank_score"] = float(score)
            results.append(reranked_doc)

        return results


class SimpleReranker:
    """
    简单重排序器（无模型依赖）
    
    基于规则的重排序，作为交叉编码器的降级方案。
    """

    def __init__(self):
        # 关键词权重
        self._keyword_weights = {
            "角色": 1.2,
            "物品": 1.2,
            "悬念": 1.1,
            "事件": 1.1,
        }

    def rerank(
        self,
        query: str,
        documents: List[Dict],
        top_k: int = 5,
    ) -> List[Dict]:
        """
        基于规则的重排序
        
        Args:
            query: 查询文本
            documents: 初步检索结果列表
            top_k: 返回前 k 个结果
            
        Returns:
            重排序后的结果列表
        """
        if not documents:
            return []

        scored_docs = []
        for doc in documents:
            score = doc.get("hybrid_score", doc.get("score", 0.0))
            content = doc.get("content", "")
            
            # 关键词匹配加分
            for keyword, weight in self._keyword_weights.items():
                if keyword in query and keyword in content:
                    score *= weight
            
            # 内容长度适中加分
            content_len = len(content)
            if 100 <= content_len <= 500:
                score *= 1.1
            
            scored_docs.append((doc, score))

        # 按分数排序
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        # 返回 top_k 结果
        results = []
        for doc, score in scored_docs[:top_k]:
            reranked_doc = doc.copy()
            reranked_doc["rerank_score"] = score
            results.append(reranked_doc)

        return results


def get_reranker(use_model: bool = True) -> object:
    """
    获取重排序器
    
    Args:
        use_model: 是否使用模型重排序
        
    Returns:
        重排序器实例
    """
    if use_model:
        reranker = CrossEncoderReranker()
        # 尝试加载模型
        reranker._load_model()
        if reranker._loaded:
            return reranker
        logger.info("降级到简单重排序器")
    
    return SimpleReranker()
