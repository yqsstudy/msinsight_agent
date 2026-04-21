"""LLM适配器基类"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncGenerator


class BaseLLMAdapter(ABC):
    """LLM适配器基类"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: str = "",
        model_name: str = "",
        parameters: Dict[str, Any] = None
    ):
        self.api_key = api_key
        self.api_url = api_url
        self.model_name = model_name
        self.parameters = parameters or {
            "temperature": 0.7,
            "max_tokens": 4096
        }

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        发送聊天请求

        Args:
            messages: 消息列表，格式: [{"role": "user", "content": "..."}]
            tools: 工具定义列表（可选）
            **kwargs: 其他参数

        Returns:
            响应结果
        """
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        流式聊天

        Args:
            messages: 消息列表
            tools: 工具定义列表（可选）
            **kwargs: 其他参数

        Yields:
            流式响应文本
        """
        pass

    def _merge_parameters(self, **kwargs) -> Dict[str, Any]:
        """合并参数"""
        params = self.parameters.copy()
        params.update(kwargs)
        return params

    def build_system_prompt(self, context: Dict[str, Any] = None) -> str:
        """构建系统提示"""
        return """你是一个AI模型性能分析助手，帮助用户分析训练和推理过程中的性能问题。

你的职责：
1. 理解用户的性能分析需求
2. 调用MCP工具进行数据分析
3. 生成诊断报告和优化建议

分析流程：
1. 解析用户提供的profiling数据
2. 检测数据类型和问题类型
3. 选择合适的分析工具
4. 生成诊断报告

当需要用户选择时（如选择通信域），请清晰地提供选项并解释原因。
"""
