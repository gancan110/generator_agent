"""知识管理模块"""

from novel_agent.knowledge.collector import KnowledgeCollector
from novel_agent.knowledge.knowledge_base import KnowledgeBase
from novel_agent.knowledge.vector_store import VectorStore
from novel_agent.knowledge.faiss_vector_store import FAISSVectorStore, create_vector_store

__all__ = [
    "KnowledgeCollector",
    "KnowledgeBase",
    "VectorStore",
    "FAISSVectorStore",
    "create_vector_store",
]
