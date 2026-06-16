"""
FAISS向量存储模块

使用FAISS替代JSON持久化，提供高性能向量检索能力。

性能对比:
├── JSON + numpy: O(n) 线性扫描
├── FAISS Flat: O(n) 但优化常数因子 (10x)
├── FAISS IVF: O(log n) 倒排索引 (100x)
└── FAISS HNSW: O(log n) 图索引 (50x)
"""

import os
import json
import logging
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from novel_agent.config import config

logger = logging.getLogger(__name__)


class FAISSVectorStore:
    """
    FAISS向量存储
    
    支持多种索引类型:
    - flat: 精确检索，适合小规模数据 (<10万)
    - ivf: 倒排索引，适合中等规模 (10-100万)
    - hnsw: 图索引，适合大规模数据 (>100万)
    """
    
    def __init__(
        self,
        project_id: int,
        dimension: int = 384,
        index_type: str = "auto",
    ):
        """
        初始化FAISS向量存储
        
        Args:
            project_id: 项目ID
            dimension: 向量维度
            index_type: 索引类型 ("auto", "flat", "ivf", "hnsw")
        """
        self.project_id = project_id
        self.dimension = dimension
        self.index_type = index_type
        
        # 存储路径
        self.store_path = Path(config.vector_db.db_path) / f"project_{project_id}"
        self.store_path.mkdir(parents=True, exist_ok=True)
        
        # FAISS索引
        self._index = None
        self._documents: List[Dict] = []
        self._id_map: Dict[int, int] = {}  # 外部ID -> 内部索引
        
        # 尝试加载已有索引
        self._load_index()
    
    def _get_faiss(self):
        """延迟导入FAISS"""
        try:
            import faiss
            return faiss
        except ImportError:
            logger.warning("faiss未安装，使用numpy降级方案")
            return None
    
    def _create_index(self, n_vectors: int = 0):
        """创建FAISS索引"""
        faiss = self._get_faiss()
        
        if faiss is None:
            # numpy降级方案
            logger.info("使用numpy向量索引")
            return None
        
        # 根据数据规模选择索引类型
        if self.index_type == "auto":
            if n_vectors < 10000:
                index_type = "flat"
            elif n_vectors < 100000:
                index_type = "ivf"
            else:
                index_type = "hnsw"
        else:
            index_type = self.index_type
        
        if index_type == "flat":
            # 精确检索
            index = faiss.IndexFlatIP(self.dimension)  # 内积相似度
            logger.info(f"创建FAISS Flat索引: dim={self.dimension}")
            
        elif index_type == "ivf":
            # 倒排索引
            nlist = min(int(np.sqrt(n_vectors)), 256)  # 聚类中心数
            quantizer = faiss.IndexFlatIP(self.dimension)
            index = faiss.IndexIVFFlat(quantizer, self.dimension, nlist)
            index.nprobe = min(nlist // 4, 32)  # 搜索的聚类数
            logger.info(f"创建FAISS IVF索引: nlist={nlist}, nprobe={index.nprobe}")
            
        elif index_type == "hnsw":
            # HNSW图索引
            M = 32  # 每个节点的连接数
            index = faiss.IndexHNSWFlat(self.dimension, M)
            index.hnsw.efSearch = 128  # 搜索深度
            logger.info(f"创建FAISS HNSW索引: M={M}")
            
        else:
            raise ValueError(f"未知索引类型: {index_type}")
        
        return index
    
    def _normalize_vectors(self, vectors: np.ndarray) -> np.ndarray:
        """L2归一化"""
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-8)
        return vectors / norms
    
    def add_documents(self, documents: List[Dict[str, str]]):
        """
        批量添加文档到向量存储
        
        Args:
            documents: 文档列表，每个文档包含content和metadata
        """
        if not documents:
            return
        
        # 提取文本
        texts = [doc.get("content", "") for doc in documents]
        
        # 文本切片
        chunks = []
        chunk_meta = []
        chunk_size = config.vector_db.chunk_size
        overlap = config.vector_db.chunk_overlap
        
        for i, doc in enumerate(documents):
            text = doc.get("content", "")
            meta = doc.get("metadata", {})
            meta["doc_index"] = i
            
            start = 0
            while start < len(text):
                end = min(start + chunk_size, len(text))
                chunk_text = text[start:end]
                if chunk_text.strip():
                    chunks.append(chunk_text)
                    chunk_meta.append({
                        **meta,
                        "chunk_start": start,
                        "chunk_end": end,
                        "full_length": len(text),
                    })
                start += chunk_size - overlap
        
        if not chunks:
            return
        
        # 编码
        vectors = self._encode(chunks)
        
        # 归一化
        vectors = self._normalize_vectors(vectors)
        
        # 创建或更新索引
        if self._index is None:
            self._index = self._create_index(len(chunks))
        
        # 添加到索引
        if self._index is not None:
            # FAISS索引
            self._index.add(vectors.astype(np.float32))
        else:
            # numpy降级方案
            if not hasattr(self, '_vectors'):
                self._vectors = vectors
            else:
                self._vectors = np.vstack([self._vectors, vectors])
        
        # 存储文档元数据
        for chunk, meta in zip(chunks, chunk_meta):
            doc_id = len(self._documents)
            self._documents.append({
                "content": chunk,
                "metadata": meta,
            })
            self._id_map[doc_id] = doc_id
        
        # 保存索引
        self._save_index()
        
        logger.info(f"已添加 {len(chunks)} 个文本切片到FAISS向量存储")
    
    def _encode(self, texts: List[str]) -> np.ndarray:
        """编码文本为向量"""
        from novel_agent.knowledge.vector_store import get_embedding_model
        
        model = get_embedding_model()
        if model is not None:
            # 分批编码
            batch_size = 64
            all_vectors = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                vecs = model.encode(batch, show_progress_bar=False)
                all_vectors.append(vecs)
            return np.vstack(all_vectors)
        else:
            # 降级方案
            return self._simple_encode(texts)
    
    def _simple_encode(self, texts: List[str]) -> np.ndarray:
        """简单编码降级方案"""
        vocab = set()
        for text in texts:
            vocab.update(text[:500])
        vocab = sorted(list(vocab))[:256]
        
        vocab_map = {ch: i for i, ch in enumerate(vocab)}
        dim = len(vocab_map)
        
        vectors = []
        for text in texts:
            vec = np.zeros(dim)
            for ch in text[:500]:
                if ch in vocab_map:
                    vec[vocab_map[ch]] += 1
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            vectors.append(vec)
        
        # 调整维度
        if dim < self.dimension:
            pad = np.zeros((len(vectors), self.dimension - dim))
            vectors = np.hstack([np.array(vectors), pad])
        elif dim > self.dimension:
            vectors = np.array(vectors)[:, :self.dimension]
        
        return np.array(vectors)
    
    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        语义相似度搜索
        
        Args:
            query: 查询文本
            top_k: 返回结果数量
            filters: 过滤条件
            
        Returns:
            搜索结果列表
        """
        if not self._documents:
            return []
        
        # 编码查询
        query_vec = self._encode([query])[0]
        query_vec = self._normalize_vectors(query_vec.reshape(1, -1))[0]
        
        # 扩大搜索范围用于过滤
        search_k = min(top_k * 3, len(self._documents))
        
        if self._index is not None:
            # FAISS搜索
            query_vec = query_vec.reshape(1, -1).astype(np.float32)
            distances, indices = self._index.search(query_vec, search_k)
            distances = distances[0]
            indices = indices[0]
        else:
            # numpy降级方案
            similarities = self._vectors @ query_vec
            top_indices = np.argsort(similarities)[::-1][:search_k]
            indices = top_indices
            distances = similarities[top_indices]
        
        # 应用过滤
        results = []
        for idx, dist in zip(indices, distances):
            if idx < 0 or idx >= len(self._documents):
                continue
            
            doc = self._documents[idx]
            meta = doc.get("metadata", {})
            
            # 应用过滤条件
            if filters:
                if not self._apply_filter(meta, filters):
                    continue
            
            results.append({
                "content": doc["content"],
                "metadata": meta,
                "similarity": float(dist),
            })
            
            if len(results) >= top_k:
                break
        
        return results
    
    def _apply_filter(self, meta: Dict, filters: Dict) -> bool:
        """应用过滤条件"""
        # type过滤
        if "type" in filters:
            if meta.get("type") != filters["type"]:
                return False
        
        # 章节号范围过滤
        ch_num = meta.get("chapter_number", -1)
        if "chapter_number_lt" in filters:
            if ch_num >= filters["chapter_number_lt"]:
                return False
        if "chapter_number_gt" in filters:
            if ch_num <= filters["chapter_number_gt"]:
                return False
        
        # 排除指定章节
        if "exclude_chapters" in filters:
            if ch_num in filters["exclude_chapters"]:
                return False
        
        return True
    
    def _save_index(self):
        """保存索引到磁盘"""
        # 保存文档元数据
        meta_file = self.store_path / "documents.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(self._documents, f, ensure_ascii=False, indent=2)
        
        # 保存FAISS索引
        if self._index is not None:
            faiss = self._get_faiss()
            if faiss is not None:
                index_file = self.store_path / "faiss.index"
                faiss.write_index(self._index, str(index_file))
                logger.info(f"FAISS索引已保存: {index_file}")
        else:
            # 保存numpy向量
            if hasattr(self, '_vectors'):
                vec_file = self.store_path / "vectors.npy"
                np.save(str(vec_file), self._vectors)
    
    def _load_index(self):
        """从磁盘加载索引"""
        # 加载文档元数据
        meta_file = self.store_path / "documents.json"
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    self._documents = json.load(f)
                logger.info(f"已加载 {len(self._documents)} 条向量记录")
            except Exception as e:
                logger.warning(f"加载文档元数据失败: {e}")
                self._documents = []
        
        # 加载FAISS索引
        faiss = self._get_faiss()
        index_file = self.store_path / "faiss.index"
        
        if faiss is not None and index_file.exists():
            try:
                self._index = faiss.read_index(str(index_file))
                logger.info(f"FAISS索引已加载: {index_file}")
                return
            except Exception as e:
                logger.warning(f"加载FAISS索引失败: {e}")
        
        # 加载numpy向量
        vec_file = self.store_path / "vectors.npy"
        if vec_file.exists():
            try:
                self._vectors = np.load(str(vec_file))
                logger.info(f"numpy向量已加载: {vec_file}")
            except Exception as e:
                logger.warning(f"加载numpy向量失败: {e}")
    
    def cleanup(self, max_documents: int = 2000):
        """清理向量索引"""
        if len(self._documents) <= max_documents:
            return
        
        # 去重
        seen_contents = set()
        unique_docs = []
        unique_vectors = []
        
        for i, doc in enumerate(self._documents):
            content_hash = hash(doc["content"][:200])
            if content_hash not in seen_contents:
                seen_contents.add(content_hash)
                unique_docs.append(doc)
                if hasattr(self, '_vectors') and i < len(self._vectors):
                    unique_vectors.append(self._vectors[i])
        
        removed = len(self._documents) - len(unique_docs)
        self._documents = unique_docs
        
        if unique_vectors:
            self._vectors = np.array(unique_vectors)
        
        # 重建索引
        if self._index is not None and len(self._documents) > 0:
            self._index = self._create_index(len(self._documents))
            vectors = self._encode([doc["content"] for doc in self._documents])
            vectors = self._normalize_vectors(vectors)
            self._index.add(vectors.astype(np.float32))
        
        self._save_index()
        
        if removed > 0:
            logger.info(f"向量索引清理: 移除 {removed} 条, 剩余 {len(self._documents)} 条")
    
    def remove_by_chapter(self, chapter_number: int) -> int:
        """删除指定章节的文档"""
        original_count = len(self._documents)
        
        # 过滤掉指定章节
        new_docs = []
        new_vectors = []
        
        for i, doc in enumerate(self._documents):
            if doc.get("metadata", {}).get("chapter_number") != chapter_number:
                new_docs.append(doc)
                if hasattr(self, '_vectors') and i < len(self._vectors):
                    new_vectors.append(self._vectors[i])
        
        removed_count = original_count - len(new_docs)
        
        if removed_count > 0:
            self._documents = new_docs
            
            if new_vectors:
                self._vectors = np.array(new_vectors)
            
            # 重建索引
            if self._index is not None and len(self._documents) > 0:
                self._index = self._create_index(len(self._documents))
                vectors = self._encode([doc["content"] for doc in self._documents])
                vectors = self._normalize_vectors(vectors)
                self._index.add(vectors.astype(np.float32))
            
            self._save_index()
            logger.info(f"已删除第 {chapter_number} 章的 {removed_count} 个切片")
        
        return removed_count
    
    def clear(self):
        """清空向量存储"""
        self._documents = []
        self._index = None
        if hasattr(self, '_vectors'):
            del self._vectors
        self._save_index()
        logger.info("向量存储已清空")
    
    @property
    def document_count(self) -> int:
        """文档数量"""
        return len(self._documents)
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "project_id": self.project_id,
            "document_count": self.document_count,
            "dimension": self.dimension,
            "index_type": self.index_type,
            "store_path": str(self.store_path),
            "has_faiss": self._index is not None,
            "has_vectors": hasattr(self, '_vectors') and self._vectors is not None,
        }


def create_vector_store(
    project_id: int,
    use_faiss: bool = True,
    **kwargs,
) -> object:
    """
    创建向量存储工厂函数
    
    Args:
        project_id: 项目ID
        use_faiss: 是否使用FAISS
        **kwargs: 额外参数
        
    Returns:
        向量存储实例
    """
    if use_faiss:
        try:
            import faiss
            return FAISSVectorStore(project_id, **kwargs)
        except ImportError:
            logger.warning("FAISS未安装，降级到numpy方案")
    
    # 降级到原有方案
    from novel_agent.knowledge.vector_store import VectorStore
    return VectorStore(project_id)
