"""
核心模块

提供事件驱动架构等基础设施。
"""

from .events import EventBus, Event, EventType, event_bus

__all__ = ["EventBus", "Event", "EventType", "event_bus"]
