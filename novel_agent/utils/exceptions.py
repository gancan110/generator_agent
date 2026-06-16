"""
自定义异常类模块

定义项目中使用的自定义异常，提供更精细的错误处理能力。
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class NovelAgentError(Exception):
    """基础异常类"""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化异常

        Args:
            message: 错误消息
            error_code: 错误代码，用于分类和识别
            details: 额外的错误详情
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "error_code": self.error_code,
            "details": self.details,
        }


class DatabaseError(NovelAgentError):
    """数据库相关异常"""
    pass


class LLMError(NovelAgentError):
    """LLM调用相关异常"""
    pass


class ValidationError(NovelAgentError):
    """数据验证异常"""
    pass


class ConfigurationError(NovelAgentError):
    """配置错误异常"""
    pass


class PipelineError(NovelAgentError):
    """流水线执行异常"""
    pass


class KnowledgeError(NovelAgentError):
    """知识采集相关异常"""
    pass


class VectorStoreError(NovelAgentError):
    """向量存储相关异常"""
    pass


class SkillError(NovelAgentError):
    """Skill系统相关异常"""
    pass


class ChapterGenerationError(PipelineError):
    """章节生成异常"""

    def __init__(
        self,
        message: str,
        chapter_number: Optional[int] = None,
        original_content: Optional[str] = None,
        **kwargs,
    ):
        """
        初始化章节生成异常

        Args:
            message: 错误消息
            chapter_number: 章节号
            original_content: 原始内容（如果有的话）
        """
        details = kwargs.get("details", {})
        if chapter_number is not None:
            details["chapter_number"] = chapter_number
        if original_content is not None:
            details["original_content_length"] = len(original_content)
        super().__init__(message, details=details, **kwargs)
        self.chapter_number = chapter_number


class QualityAssessmentError(PipelineError):
    """质量评估异常"""

    def __init__(
        self,
        message: str,
        content_length: Optional[int] = None,
        **kwargs,
    ):
        """
        初始化质量评估异常

        Args:
            message: 错误消息
            content_length: 内容长度
        """
        details = kwargs.get("details", {})
        if content_length is not None:
            details["content_length"] = content_length
        super().__init__(message, details=details, **kwargs)


class OutlineError(PipelineError):
    """大纲相关异常"""
    pass


class MemoryError(NovelAgentError):
    """记忆系统异常"""
    pass


class SuspenseError(NovelAgentError):
    """悬念管理异常"""
    pass


class AssetError(NovelAgentError):
    """资产管理异常"""
    pass


def handle_error(
    error: Exception,
    context: Optional[str] = None,
    raise_error: bool = False,
    default_value: Any = None,
) -> Any:
    """
    统一错误处理函数

    Args:
        error: 捕获的异常
        context: 错误上下文描述
        raise_error: 是否重新抛出异常
        default_value: 出错时返回的默认值

    Returns:
        出错时返回默认值

    Raises:
        如果 raise_error 为 True，重新抛出异常
    """
    error_msg = f"{context}: {str(error)}" if context else str(error)

    # 根据异常类型选择日志级别
    if isinstance(error, (DatabaseError, LLMError, ConfigurationError)):
        logger.error(error_msg, exc_info=True)
    elif isinstance(error, (ValidationError, KnowledgeError)):
        logger.warning(error_msg)
    else:
        logger.warning(error_msg, exc_info=True)

    if raise_error:
        if isinstance(error, NovelAgentError):
            raise error
        else:
            # 包装为 NovelAgentError
            raise NovelAgentError(
                message=error_msg,
                details={"original_exception": type(error).__name__},
            )

    return default_value
