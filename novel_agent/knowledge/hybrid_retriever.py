"""
混合检索模块

结合语义检索（向量相似度）和关键词检索（BM25），
提供更全面的检索能力。
"""

import logging
import math
import re
from typing import Dict, List, Optional, Tuple
from collections import Counter

logger = logging.getLogger(__name__)


class BM25Scorer:
    """
    BM25 评分器
    
    用于中文文本的关键词检索。
    使用 jieba 进行分词。
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        """
        Args:
            k1: 词频饱和参数
            b: 文档长度归一化参数
        """
        self.k1 = k1
        self.b = b
        self._documents: List[List[str]] = []
        self._doc_lengths: List[int] = []
        self._avg_doc_length: float = 0.0
        self._df: Counter = Counter()  # 文档频率
        self._n_docs: int = 0

    def _tokenize(self, text: str) -> List[str]:
        """中文分词"""
        try:
            import jieba
            # 停用词
            stopwords = {
                '的', '了', '在', '是', '我', '有', '和', '就', '不', '人',
                '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去',
                '你', '会', '着', '没有', '看', '好', '自己', '这', '他', '她',
                '它', '们', '那', '被', '从', '把', '对', '让', '给', '又',
            }
            tokens = jieba.lcut(text)
            return [t for t in tokens if t.strip() and t not in stopwords and len(t) > 1]
        except ImportError:
            # 降级：按字符分词
            return list(text)

    def index(self, documents: List[str]):
        """
        索引文档
        
        Args:
            documents: 文档列表
        """
        self._documents = []
        self._doc_lengths = []
        self._df = Counter()
        self._n_docs = len(documents)

        for doc in documents:
            tokens = self._tokenize(doc)
            self._documents.append(tokens)
            self._doc_lengths.append(len(tokens))
            
            # 统计文档频率（每个词只计一次）
            unique_tokens = set(tokens)
            for token in unique_tokens:
                self._df[token] += 1

        # 计算平均文档长度
        if self._n_docs > 0:
            self._avg_doc_length = sum(self._doc_lengths) / self._n_docs
        else:
            self._avg_doc_length = 0.0

        logger.debug(f"BM25 索引完成: {self._n_docs} 篇文档, 平均长度 {self._avg_doc_length:.0f}")

    def score(self, query: str, top_k: int = 10) -> List[Tuple[int, float]]:
        """
        计算查询与所有文档的 BM25 分数
        
        Args:
            query: 查询文本
            top_k: 返回前 k 个结果
            
        Returns:
            [(文档索引, 分数), ...] 按分数降序排列
        """
        query_tokens = self._tokenize(query)
        if not query_tokens or self._n_docs == 0:
            return []

        scores = []
        for i, doc_tokens in enumerate(self._documents):
            score = self._compute_doc_score(query_tokens, i, doc_tokens)
            if score > 0:
                scores.append((i, score))

        # 按分数降序排列
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def _compute_doc_score(
        self, query_tokens: List[str], doc_idx: int, doc_tokens: List[str]
    ) -> float:
        """计算单个文档的 BM25 分数"""
        doc_len = self._doc_lengths[doc_idx]
        doc_tf = Counter(doc_tokens)
        
        score = 0.0
        for token in query_tokens:
            if token not in self._df:
                continue
            
            # IDF 部分
            df = self._df[token]
            idf = math.log((self._n_docs - df + 0.5) / (df + 0.5) + 1)
            
            # TF 部分
            tf = doc_tf.get(token, 0)
            if tf == 0:
                continue
            
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self._avg_doc_length)
            tf_score = numerator / denominator
            
            score += idf * tf_score
        
        return score


class HybridRetriever:
    """
    混合检索器
    
    结合语义检索和关键词检索，提供更全面的检索能力。
    """

    def __init__(self, alpha: float = 0.7):
        """
        Args:
            alpha: 语义检索权重 (0-1)，1-alpha 为关键词检索权重
        """
        self.alpha = alpha
        self._bm25 = BM25Scorer()
        self._documents: List[Dict] = []
        self._indexed = False

    def index(self, documents: List[Dict]):
        """
        索引文档
        
        Args:
            documents: 文档列表，每个文档包含 content 和 metadata
        """
        self._documents = documents
        contents = [doc.get("content", "") for doc in documents]
        self._bm25.index(contents)
        self._indexed = True
        logger.debug(f"混合检索索引完成: {len(documents)} 篇文档")

    def search(
        self,
        query: str,
        semantic_scores: List[Tuple[int, float]],
        top_k: int = 5,
    ) -> List[Dict]:
        """
        混合检索
        
        Args:
            query: 查询文本
            semantic_scores: 语义检索结果 [(文档索引, 相似度分数), ...]
            top_k: 返回前 k 个结果
            
        Returns:
            混合检索结果列表
        """
        if not self._indexed:
            logger.warning("混合检索器未索引")
            return []

        # 获取 BM25 分数
        bm25_scores = self._bm25.score(query, top_k=len(self._documents))

        # 归一化分数
        semantic_normalized = self._normalize_scores(semantic_scores)
        bm25_normalized = self._normalize_scores(bm25_scores)

        # 合并分数
        merged_scores: Dict[int, float] = {}
        for idx, score in semantic_normalized:
            merged_scores[idx] = merged_scores.get(idx, 0) + self.alpha * score
        for idx, score in bm25_normalized:
            merged_scores[idx] = merged_scores.get(idx, 0) + (1 - self.alpha) * score

        # 排序
        sorted_results = sorted(merged_scores.items(), key=lambda x: x[1], reverse=True)

        # 构建结果
        results = []
        for idx, score in sorted_results[:top_k]:
            if idx < len(self._documents):
                doc = self._documents[idx].copy()
                doc["hybrid_score"] = score
                results.append(doc)

        return results

    def _normalize_scores(self, scores: List[Tuple[int, float]]) -> List[Tuple[int, float]]:
        """归一化分数到 [0, 1]"""
        if not scores:
            return []
        
        max_score = max(s for _, s in scores)
        min_score = min(s for _, s in scores)
        
        if max_score == min_score:
            return [(idx, 1.0) for idx, _ in scores]
        
        return [(idx, (score - min_score) / (max_score - min_score)) for idx, score in scores]
