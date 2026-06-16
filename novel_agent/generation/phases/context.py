"""
Pipeline 上下文数据类

集中管理所有子系统引用，供各阶段执行器使用。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class PipelineContext:
    """
    管道上下文 - 持有所有子系统实例的引用
    
    各阶段执行器通过此上下文访问所需子系统，
    避免直接持有 GenerationPipeline 的引用。
    """
    # 项目信息
    project_id: int = 0
    project_name: str = ""
    
    # 知识库子系统
    knowledge_base: Any = None
    vector_store: Any = None
    knowledge_collector: Any = None
    
    # 生成子系统
    outline_generator: Any = None
    outline_updater: Any = None
    chapter_generator: Any = None
    chapter_rewriter: Any = None
    
    # 管理子系统
    memory_manager: Any = None
    character_manager: Any = None
    item_manager: Any = None
    world_setting_manager: Any = None
    suspense_manager: Any = None
    
    # 评估子系统
    quality_evaluator: Any = None
    parameter_optimizer: Any = None
    
    # 配置
    skill_context: Any = None
    config: Any = None
    
    # 运行时状态
    current_outline: Optional[Dict] = None
