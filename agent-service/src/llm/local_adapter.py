"""本地模型适配器"""

from typing import List, Dict, Any, AsyncGenerator
import json
import httpx

from .base import BaseLLMAdapter


class LocalAdapter(BaseLLMAdapter):
    """本地模型适配器（兼容OpenAI API格式）"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._client = httpx.AsyncClient(timeout=120.0)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """发送聊天请求"""
        params = self._merge_parameters(**kwargs)

        request_body = {
            "model": self.model_name or "local-model",
            "messages": messages,
            **params
        }

        if tools:
            request_body["tools"] = self._convert_tools(tools)

        url = f"{self.api_url}/chat/completions"
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = await self._client.post(
            url,
            json=request_body,
            headers=headers
        )
        response.raise_for_status()

        return self._parse_response(response.json())

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式聊天"""
        params = self._merge_parameters(**kwargs)

        request_body = {
            "model": self.model_name or "local-model",
            "messages": messages,
            "stream": True,
            **params
        }

        url = f"{self.api_url}/chat/completions"
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with self._client.stream(
            "POST",
            url,
            json=request_body,
            headers=headers
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        if chunk.get("choices") and chunk["choices"][0].get("delta", {}).get("content"):
                            yield chunk["choices"][0]["delta"]["content"]
                    except json.JSONDecodeError:
                        continue

    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """转换工具格式"""
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

    def _parse_response(self, response: dict) -> Dict[str, Any]:
        """解析响应"""
        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})

        result = {
            "content": message.get("content", ""),
            "tool_calls": [],
            "finish_reason": choice.get("finish_reason", "stop")
        }

        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                result["tool_calls"].append({
                    "id": tc.get("id"),
                    "name": tc.get("function", {}).get("name"),
                    "arguments": tc.get("function", {}).get("arguments")
                })

        return result

    async def close(self):
        """关闭客户端"""
        await self._client.aclose()
