"""
事件总线模块

提供发布-订阅模式的事件驱动架构，解耦子系统间的直接依赖。
"""

import logging
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import threading

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """事件数据类"""
    type: str                           # 事件类型
    data: Dict[str, Any] = field(default_factory=dict)  # 事件数据
    source: str = ""                    # 事件来源
    timestamp: float = 0.0              # 时间戳（可选）


# 事件类型常量
class EventType:
    # 章节相关
    CHAPTER_STARTED = "chapter.started"
    CHAPTER_COMPLETED = "chapter.completed"
    CHAPTER_REWRITTEN = "chapter.rewritten"
    
    # 知识相关
    KNOWLEDGE_COLLECTED = "knowledge.collected"
    WORLDVIEW_GENERATED = "worldview.generated"
    
    # 大纲相关
    OUTLINE_GENERATED = "outline.generated"
    OUTLINE_UPDATED = "outline.updated"
    
    # 资产相关
    CHARACTER_CREATED = "character.created"
    CHARACTER_UPDATED = "character.updated"
    ITEM_CREATED = "item.created"
    ITEM_UPDATED = "item.updated"
    
    # 悬念相关
    SUSPENSE_CREATED = "suspense.created"
    SUSPENSE_RESOLVED = "suspense.resolved"
    
    # 质量相关
    QUALITY_EVALUATED = "quality.evaluated"
    QUALITY_LOW = "quality.low"
    
    # 记忆相关
    MEMORY_COMPRESSED = "memory.compressed"
    
    # 系统相关
    PIPELINE_STARTED = "pipeline.started"
    PIPELINE_COMPLETED = "pipeline.completed"
    PIPELINE_ERROR = "pipeline.error"


class EventBus:
    """
    事件总线
    
    支持：
    - 同步/异步事件处理
    - 事件过滤
    - 事件历史记录
    """

    def __init__(self, max_history: int = 1000):
        """
        Args:
            max_history: 最大事件历史记录数
        """
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._history: List[Event] = []
        self._max_history = max_history
        self._lock = threading.Lock()
        self._enabled = True

    def subscribe(self, event_type: str, handler: Callable[[Event], None]):
        """
        订阅事件
        
        Args:
            event_type: 事件类型（支持通配符 '*' 匹配所有事件）
            handler: 事件处理函数
        """
        with self._lock:
            self._handlers[event_type].append(handler)
            logger.debug(f"已订阅事件: {event_type}")

    def unsubscribe(self, event_type: str, handler: Callable[[Event], None]):
        """取消订阅"""
        with self._lock:
            if event_type in self._handlers:
                self._handlers[event_type] = [
                    h for h in self._handlers[event_type] if h != handler
                ]

    def publish(self, event: Event):
        """
        发布事件
        
        Args:
            event: 事件对象
        """
        if not self._enabled:
            return
        
        # 记录历史
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
        
        # 获取匹配的处理器
        handlers = self._get_matching_handlers(event.type)
        
        # 执行处理器
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"事件处理失败 ({event.type}): {e}")

    def emit(self, event_type: str, data: Dict[str, Any] = None, source: str = ""):
        """
        快捷发布事件
        
        Args:
            event_type: 事件类型
            data: 事件数据
            source: 事件来源
        """
        import time
        event = Event(
            type=event_type,
            data=data or {},
            source=source,
            timestamp=time.time(),
        )
        self.publish(event)

    def _get_matching_handlers(self, event_type: str) -> List[Callable]:
        """获取匹配事件类型的所有处理器"""
        handlers = []
        
        # 精确匹配
        if event_type in self._handlers:
            handlers.extend(self._handlers[event_type])
        
        # 通配符匹配
        if "*" in self._handlers:
            handlers.extend(self._handlers["*"])
        
        return handlers

    def get_history(self, event_type: str = None, limit: int = 100) -> List[Event]:
        """获取事件历史"""
        with self._lock:
            if event_type:
                events = [e for e in self._history if e.type == event_type]
            else:
                events = self._history.copy()
            return events[-limit:]

    def clear_history(self):
        """清空事件历史"""
        with self._lock:
            self._history.clear()

    def enable(self):
        """启用事件总线"""
        self._enabled = True

    def disable(self):
        """禁用事件总线"""
        self._enabled = False


# 全局事件总线单例
event_bus = EventBus()
