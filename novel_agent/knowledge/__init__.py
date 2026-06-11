"""知识管理模块"""

from novel_agent.knowledge.collector import KnowledgeCollector
from novel_agent.knowledge.knowledge_base import KnowledgeBase
from novel_agent.knowledge.vector_store import VectorStore

__all__ = ["KnowledgeCollector", "KnowledgeBase", "VectorStore"]
