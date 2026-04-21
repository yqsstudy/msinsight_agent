"""OpenAI适配器"""

from typing import List, Dict, Any, Optional, AsyncGenerator

from .base import BaseLLMAdapter


class OpenAIAdapter(BaseLLMAdapter):
    """OpenAI API适配器"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._client = None

    def _get_client(self):
        """懒加载客户端"""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    api_key=self.api_key,
                    base_url=self.api_url if self.api_url else None
                )
            except ImportError:
                raise ImportError("请安装openai库: pip install openai")
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

        request_params = {
            "model": self.model_name or "gpt-4",
            "messages": messages,
            **params
        }

        if tools:
            request_params["tools"] = self._convert_tools(tools)

        response = await client.chat.completions.create(**request_params)

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

        request_params = {
            "model": self.model_name or "gpt-4",
            "messages": messages,
            "stream": True,
            **params
        }

        stream = await client.chat.completions.create(**request_params)

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """转换工具格式为OpenAI格式"""
        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name"),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {})
                }
            })
        return openai_tools

    def _parse_response(self, response) -> Dict[str, Any]:
        """解析响应"""
        choice = response.choices[0]
        result = {
            "content": choice.message.content or "",
            "tool_calls": [],
            "finish_reason": choice.finish_reason
        }

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                result["tool_calls"].append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                })

        return result
