"""
向量存储模块

将小说创作知识向量化存储，支持语义相似度检索。
使用 sentence-transformers 进行文本向量化，FAISS 进行向量索引。

性能优化：
- 模块级单例：模型只加载一次，跨所有 VectorStore 实例共享
- 后台预加载：在 import 后立即启动后台线程加载模型
- ONNX 后端：自动检测 optimum 并启用更快的推理后端
- 批量编码：大文档自动分批编码，避免内存溢出
"""

import os
import json
import logging
import threading
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from novel_agent.config import config

logger = logging.getLogger(__name__)


# ============================================================
# 模块级模型单例 — 全局只加载一次
# ============================================================
_global_model = None
_global_model_lock = threading.Lock()
_global_model_loading = False  # 标记是否已有线程在加载
_global_model_failed = False
_model_name = config.vector_db.embedding_model


def _detect_best_backend() -> str:
    """
    检测最佳推理后端。
    
    注意：ONNX 后端虽然在单次编码上更快（~27ms vs ~167ms），
    但首次加载需要模型转换（~135s），即使缓存后也需 ~17s，
    而 torch 默认后端加载仅需 ~14s，且批量编码性能相当。
    因此默认使用 torch 后端，ONNX 仅在显式配置时启用。
    """
    use_onnx = os.getenv("EMBEDDING_BACKEND", "").lower() == "onnx"
    if use_onnx:
        try:
            import optimum.onnxruntime  # noqa: F401
            logger.info("使用 ONNX 后端（通过 EMBEDDING_BACKEND=onnx 显式启用）")
            return "onnx"
        except ImportError:
            logger.warning("optimum 未安装，回退到 torch 后端")
    return "torch"


def preload_embedding_model():
    """
    在后台线程预加载 embedding 模型。

    建议在应用启动时（如 pipeline.initialize()）调用，
    让模型加载与 MySQL 连接、知识库采集等操作并行执行。
    """
    global _global_model_loading

    with _global_model_lock:
        if _global_model is not None or _global_model_loading or _global_model_failed:
            return
        _global_model_loading = True

    thread = threading.Thread(target=_do_load_model, daemon=True, name="embed-preload")
    thread.start()


def _do_load_model():
    """实际执行模型加载（在后台线程中运行）"""
    global _global_model, _global_model_loading, _global_model_failed

    try:
        import time
        t0 = time.time()

        from sentence_transformers import SentenceTransformer

        backend = _detect_best_backend()
        kwargs = {}
        if backend == "onnx":
            kwargs["backend"] = "onnx"

        model = SentenceTransformer(_model_name, **kwargs)

        # 预热：跑一次空编码，触发内部图编译
        model.encode(["warmup"], show_progress_bar=False)

        elapsed = time.time() - t0
        logger.info(
            f"Embedding 模型已加载 ({backend} 后端): "
            f"{_model_name}，耗时 {elapsed:.1f}s"
        )

        with _global_model_lock:
            _global_model = model
            _global_model_loading = False

    except ImportError:
        logger.warning(
            "sentence-transformers 未安装，将使用简单编码模式。"
            "请运行: pip install sentence-transformers"
        )
        with _global_model_lock:
            _global_model_failed = True
            _global_model_loading = False
    except Exception as e:
        logger.warning(
            f"Embedding 模型加载失败 ({type(e).__name__})，"
            f"使用简单编码模式。错误: {e}"
        )
        with _global_model_lock:
            _global_model_failed = True
            _global_model_loading = False


def get_embedding_model():
    """
    获取全局 embedding 模型（同步版本）。

    如果后台预加载已启动，此方法会等待加载完成。
    如果未启动预加载，则在此处同步加载。
    """
    global _global_model, _global_model_loading, _global_model_failed

    # 快速路径：已加载
    if _global_model is not None:
        return _global_model

    # 已失败
    if _global_model_failed:
        return None

    # 后台正在加载 → 等待
    if _global_model_loading:
        logger.info("等待后台模型加载完成...")
        while _global_model_loading:
            import time
            time.sleep(0.2)
        return _global_model

    # 没有后台加载 → 同步加载
    with _global_model_lock:
        if _global_model is not None:
            return _global_model
        if _global_model_failed:
            return None
        _global_model_loading = True

    _do_load_model()
    return _global_model


# ============================================================
# VectorStore 类
# ============================================================
class VectorStore:
    """
    向量存储与检索

    功能：
    - 文本向量化（使用 sentence-transformers 全局单例）
    - 向量索引（JSON 持久化 + numpy 计算）
    - 语义相似度检索（余弦相似度）
    """

    def __init__(self, project_id: int):
        """
        Args:
            project_id: 关联的项目 ID
        """
        self.project_id = project_id
        self.store_path = Path(config.vector_db.db_path) / f"project_{project_id}"
        self.store_path.mkdir(parents=True, exist_ok=True)

        self._documents: List[Dict] = []
        self._vectors: Optional[np.ndarray] = None
        self._vectors_dirty = False  # 标记 numpy 缓存是否需要重建

        # 尝试加载已有数据
        self._load_index()

    def _encode(self, texts: List[str]) -> np.ndarray:
        """
        将文本列表编码为向量矩阵

        Args:
            texts: 文本列表

        Returns:
            向量矩阵 (n, dim)
        """
        model = get_embedding_model()
        if model is not None:
            # 分批编码以避免大文档集的内存问题
            batch_size = 64
            if len(texts) <= batch_size:
                return model.encode(texts, show_progress_bar=False)
            else:
                all_vectors = []
                for i in range(0, len(texts), batch_size):
                    batch = texts[i:i + batch_size]
                    vecs = model.encode(batch, show_progress_bar=False)
                    all_vectors.append(vecs)
                return np.vstack(all_vectors)
        else:
            return self._simple_encode(texts)

    def _simple_encode(self, texts: List[str]) -> np.ndarray:
        """简单的文本编码降级方案（字符频率 + L2 归一化）"""
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

        return np.array(vectors)

    def _get_vectors_matrix(self) -> Optional[np.ndarray]:
        """获取所有文档向量的 numpy 矩阵（带缓存）"""
        if not self._documents:
            return None

        if self._vectors is not None and not self._vectors_dirty:
            return self._vectors

        self._vectors = np.array([doc["vector"] for doc in self._documents])
        self._vectors_dirty = False
        return self._vectors

    def add_documents(self, documents: List[Dict[str, str]]):
        """
        批量添加文档到向量存储

        Args:
            documents: 文档列表，每个文档是一个字典，
                      必须包含 'content' 字段，可选包含 'metadata' 字段
        """
        if not documents:
            return

        texts = [doc["content"] for doc in documents]

        # 文本切片
        chunks = []
        chunk_meta = []
        chunk_size = config.vector_db.chunk_size
        overlap = config.vector_db.chunk_overlap

        for i, doc in enumerate(documents):
            text = doc["content"]
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

        # 存储
        for chunk, meta, vec in zip(chunks, chunk_meta, vectors):
            self._documents.append({
                "content": chunk,
                "metadata": meta,
                "vector": vec.tolist(),
            })

        self._vectors_dirty = True
        self._save_index()
        logger.info(f"已添加 {len(chunks)} 个文本切片到向量存储")

    def search(self, query: str, top_k: int = 5, filters: Optional[Dict] = None) -> List[Dict]:
        """
        语义相似度搜索（使用矩阵运算加速）

        Args:
            query: 查询文本
            top_k: 返回结果数量
            filters: 可选的 metadata 过滤条件
                - chapter_number_lt: 只返回章节号 < N 的结果
                - chapter_number_gt: 只返回章节号 > N 的结果
                - type: 只返回指定 type 的结果（如 "chapter", "knowledge"）
                - exclude_chapters: 排除指定章节号列表

        Returns:
            最相关的文档列表
        """
        if not self._documents:
            return []

        # 编码查询
        query_vec = self._encode([query])[0]

        # 构建候选索引列表（应用过滤条件）
        candidate_indices = self._apply_filters(filters) if filters else list(range(len(self._documents)))

        if not candidate_indices:
            return []

        # 提取候选向量
        candidate_vectors = np.array([self._documents[i]["vector"] for i in candidate_indices])

        # 批量余弦相似度
        query_norm = np.linalg.norm(query_vec)
        doc_norms = np.linalg.norm(candidate_vectors, axis=1)
        similarities = candidate_vectors @ query_vec / (
            doc_norms * query_norm + 1e-8
        )

        # 取 top_k
        top_local_indices = np.argsort(similarities)[::-1][:top_k]

        results = []
        for local_idx in top_local_indices:
            global_idx = candidate_indices[local_idx]
            results.append({
                "content": self._documents[global_idx]["content"],
                "metadata": self._documents[global_idx]["metadata"],
                "similarity": float(similarities[local_idx]),
            })
        return results

    def _apply_filters(self, filters: Dict) -> List[int]:
        """
        根据 metadata 过滤条件返回匹配的文档索引列表

        支持的过滤器:
        - chapter_number_lt (int): 章节号 < N
        - chapter_number_gt (int): 章节号 > N
        - type (str): metadata type 等于指定值
        - exclude_chapters (list[int]): 排除指定章节号
        - min_similarity (float): 预过滤（在搜索后应用）
        """
        indices = []
        for i, doc in enumerate(self._documents):
            meta = doc.get("metadata", {})

            # type 过滤
            if "type" in filters:
                if meta.get("type") != filters["type"]:
                    continue

            # 章节号范围过滤
            ch_num = meta.get("chapter_number", -1)
            if "chapter_number_lt" in filters:
                if ch_num >= filters["chapter_number_lt"]:
                    continue
            if "chapter_number_gt" in filters:
                if ch_num <= filters["chapter_number_gt"]:
                    continue

            # 排除指定章节
            if "exclude_chapters" in filters:
                if ch_num in filters["exclude_chapters"]:
                    continue

            indices.append(i)
        return indices

    def cleanup(self, max_documents: int = 2000, min_similarity_threshold: float = 0.05):
        """
        清理向量索引，移除低质量或冗余的文档切片

        策略：
        1. 移除重复内容（完全相同的切片）
        2. 如果总文档数超过 max_documents，移除最旧的知识类切片

        Args:
            max_documents: 最大文档切片数
            min_similarity_threshold: 未使用（保留供未来扩展）
        """
        if len(self._documents) <= max_documents:
            return

        # 去重：基于内容哈希
        seen_contents = set()
        unique_docs = []
        for doc in self._documents:
            content_hash = hash(doc["content"][:200])  # 用前200字符做快速去重
            if content_hash not in seen_contents:
                seen_contents.add(content_hash)
                unique_docs.append(doc)

        removed_dedup = len(self._documents) - len(unique_docs)

        # 如果去重后仍然超限，按优先级裁剪
        if len(unique_docs) > max_documents:
            # 优先级：chapter > knowledge（知识类文档可以更多裁剪）
            chapter_docs = [d for d in unique_docs if d.get("metadata", {}).get("type") == "chapter"]
            other_docs = [d for d in unique_docs if d.get("metadata", {}).get("type") != "chapter"]

            # 保留所有 chapter 文档，裁剪 other 文档
            max_other = max(0, max_documents - len(chapter_docs))
            unique_docs = chapter_docs + other_docs[:max_other]

        removed_total = len(self._documents) - len(unique_docs)
        self._documents = unique_docs
        self._vectors_dirty = True
        self._save_index()

        if removed_total > 0:
            logger.info(
                f"向量索引清理: 去重 {removed_dedup} 条, "
                f"总计移除 {removed_total} 条, 剩余 {len(unique_docs)} 条"
            )

    def _save_index(self):
        """保存向量索引到磁盘"""
        index_file = self.store_path / "index.json"
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(self._documents, f, ensure_ascii=False, indent=2)

    def _load_index(self):
        """从磁盘加载向量索引"""
        index_file = self.store_path / "index.json"
        if index_file.exists():
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    self._documents = json.load(f)
                self._vectors_dirty = True
                logger.info(f"已加载 {len(self._documents)} 条向量记录")
            except Exception as e:
                logger.warning(f"加载向量索引失败: {e}")
                self._documents = []

    @property
    def document_count(self) -> int:
        """存储的文档切片数量"""
        return len(self._documents)

    def clear(self):
        """清空向量存储"""
        self._documents = []
        self._vectors = None
        self._vectors_dirty = False
        self._save_index()
        logger.info("向量存储已清空")

    def remove_by_chapter(self, chapter_number: int) -> int:
        """
        删除指定章节的所有文档切片

        Args:
            chapter_number: 要删除的章节号

        Returns:
            删除的文档数量
        """
        original_count = len(self._documents)
        self._documents = [
            doc for doc in self._documents
            if doc.get("metadata", {}).get("chapter_number") != chapter_number
        ]
        removed_count = original_count - len(self._documents)
        if removed_count > 0:
            self._vectors_dirty = True
            self._save_index()
            logger.info(f"已从向量存储删除第 {chapter_number} 章的 {removed_count} 个切片")
        return removed_count
