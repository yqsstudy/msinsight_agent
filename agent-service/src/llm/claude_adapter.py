"""Claude适配器"""

from typing import List, Dict, Any, Optional, AsyncGenerator

from .base import BaseLLMAdapter


class ClaudeAdapter(BaseLLMAdapter):
    """Claude API适配器"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._client = None

    def _get_client(self):
        """懒加载客户端"""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError("请安装anthropic库: pip install anthropic")
        return self._client

    async def chat(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """发送聊天请求"""
        client = self._get_client()
        params = self._merge_parameters(**kwargs)

        # 提取系统消息
        system_prompt = None
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                chat_messages.append(msg)

        request_params = {
            "model": self.model_name or "claude-sonnet-4-6",
            "messages": chat_messages,
            **params
        }

        if system_prompt:
            request_params["system"] = system_prompt

        if tools:
            request_params["tools"] = self._convert_tools(tools)

        response = await client.messages.create(**request_params)

        return self._parse_response(response)

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式聊天"""
        client = self._get_client()
        params = self._merge_parameters(**kwargs)

        system_prompt = None
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                chat_messages.append(msg)

        request_params = {
            "model": self.model_name or "claude-sonnet-4-6",
            "messages": chat_messages,
            **params
        }

        if system_prompt:
            request_params["system"] = system_prompt

        async with client.messages.stream(**request_params) as stream:
            async for text in stream.text_stream:
                yield text

    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """转换工具格式为Claude格式"""
        claude_tools = []
        for tool in tools:
            claude_tools.append({
                "name": tool.get("name"),
                "description": tool.get("description", ""),
                "input_schema": tool.get("parameters", {})
            })
        return claude_tools

    def _parse_response(self, response) -> Dict[str, Any]:
        """解析响应"""
        result = {
            "content": "",
            "tool_calls": [],
            "finish_reason": "stop"
        }

        for block in response.content:
            if hasattr(block, 'text'):
                result["content"] += block.text
            elif hasattr(block, 'type') and block.type == 'tool_use':
                result["tool_calls"].append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input
                })
                result["finish_reason"] = "tool_calls"

        return result
