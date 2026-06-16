"""
LLM 客户端工具

封装与 Agnes AI API 的交互，提供统一的文本生成接口。
支持流式输出、重试机制和错误处理。
"""

import time
import logging
from typing import Optional
from openai import OpenAI

from novel_agent.config import config

logger = logging.getLogger(__name__)


class LLMClient:
    """
    LLM 客户端 - 封装 Agnes AI API 调用

    提供统一的文本生成接口，内置重试和错误处理机制。
    """

    def __init__(self):
        """初始化 LLM 客户端"""
        self._client = OpenAI(
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
        )
        self.model = config.llm.model
        self.max_retries = config.llm.max_retries
        self.timeout = config.llm.timeout

    def generate(
        self,
        prompt: str,
        system_prompt: str = "你是一位专业的小说创作助手。",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        context: Optional[dict] = None,
    ) -> str:
        """
        生成文本内容

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词，设定AI角色和行为
            temperature: 温度参数，控制生成的随机性（0-1）
            max_tokens: 最大生成token数
            context: 可选的上下文信息，会附加到系统提示中

        Returns:
            生成的文本内容

        Raises:
            RuntimeError: API调用失败时抛出
        """
        # 构建系统消息
        system_message = system_prompt
        if context:
            context_str = "\n".join(
                f"【{k}】\n{v}" for k, v in context.items() if v
            )
            system_message += f"\n\n以下是相关参考信息：\n{context_str}"

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ]

        # 带重试的API调用
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(
                    f"LLM调用 [尝试 {attempt}/{self.max_retries}] "
                    f"model={self.model} temp={temperature}"
                )

                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=self.timeout,
                )

                content = response.choices[0].message.content
                logger.info(f"LLM生成完成，输出长度: {len(content)} 字符")
                return content

            except Exception as e:
                last_error = e
                logger.warning(
                    f"LLM调用失败 [尝试 {attempt}/{self.max_retries}]: {e}"
                )
                if attempt < self.max_retries:
                    wait_time = 2 ** attempt  # 指数退避
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)

        raise RuntimeError(
            f"LLM调用在 {self.max_retries} 次尝试后仍然失败: {last_error}"
        )

    def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "你是一位专业的小说创作助手。",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        context: Optional[dict] = None,
    ):
        """
        流式生成文本内容（逐 chunk 产出）

        Yields:
            str: 生成的文本片段
        """
        system_message = system_prompt
        if context:
            context_str = "\n".join(
                f"【{k}】\n{v}" for k, v in context.items() if v
            )
            system_message += f"\n\n以下是相关参考信息：\n{context_str}"

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ]

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=self.timeout,
                    stream=True,
                )
                for chunk in response:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        yield delta.content
                return
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)

        raise RuntimeError(
            f"LLM流式调用在 {self.max_retries} 次尝试后失败: {last_error}"
        )

    def generate_structured(
        self,
        prompt: str,
        system_prompt: str = "你是一位专业的小说创作助手。请以JSON格式输出。",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        context: Optional[dict] = None,
    ) -> str:
        """
        生成结构化内容（如JSON格式的大纲、角色档案等）

        与 generate() 类似，但默认使用较低温度以确保输出格式稳定。

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大生成token数
            context: 可选的上下文信息

        Returns:
            生成的结构化文本内容
        """
        return self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            context=context,
        )


# 全局 LLM 客户端单例
llm_client = LLMClient()
