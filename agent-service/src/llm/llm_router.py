"""LLM路由器 - 根据配置选择合适的LLM适配器"""

from typing import Dict, Any, List, Optional, AsyncGenerator

from .base import BaseLLMAdapter
from .claude_adapter import ClaudeAdapter
from .openai_adapter import OpenAIAdapter
from .local_adapter import LocalAdapter


class LLMRouter:
    """LLM路由器"""

    ADAPTER_MAP = {
        "claude": ClaudeAdapter,
        "openai": OpenAIAdapter,
        "local": LocalAdapter,
    }

    def __init__(self, config: Dict[str, Any] = None):
        """
        Args:
            config: LLM配置，格式:
                {
                    "default_provider": "claude",
                    "providers": {
                        "claude": {"api_key": "...", "model": "..."},
                        "openai": {"api_key": "...", "model": "..."},
                        "local": {"api_url": "..."}
                    }
                }
        """
        self.config = config or {}
        self._adapters: Dict[str, BaseLLMAdapter] = {}

    def get_adapter(self, provider: str = None) -> BaseLLMAdapter:
        """获取指定provider的适配器"""
        provider = provider or self.config.get("default_provider", "claude")

        if provider not in self._adapters:
            self._adapters[provider] = self._create_adapter(provider)

        return self._adapters[provider]

    def _create_adapter(self, provider: str) -> BaseLLMAdapter:
        """创建适配器实例"""
        if provider not in self.ADAPTER_MAP:
            raise ValueError(f"Unknown provider: {provider}")

        adapter_class = self.ADAPTER_MAP[provider]
        provider_config = self.config.get("providers", {}).get(provider, {})

        return adapter_class(
            api_key=provider_config.get("api_key"),
            api_url=provider_config.get("api_url"),
            model_name=provider_config.get("model"),
            parameters=provider_config.get("parameters")
        )

    async def chat(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]] = None,
        provider: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """发送聊天请求"""
        adapter = self.get_adapter(provider)
        return await adapter.chat(messages, tools, **kwargs)

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]] = None,
        provider: str = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式聊天"""
        adapter = self.get_adapter(provider)
        async for chunk in adapter.chat_stream(messages, tools, **kwargs):
            yield chunk

    def update_config(self, provider: str, config: Dict[str, Any]):
        """更新provider配置"""
        if "providers" not in self.config:
            self.config["providers"] = {}

        self.config["providers"][provider] = config

        # 清除缓存的适配器
        if provider in self._adapters:
            del self._adapters[provider]

    def set_default_provider(self, provider: str):
        """设置默认provider"""
        if provider not in self.ADAPTER_MAP:
            raise ValueError(f"Unknown provider: {provider}")
        self.config["default_provider"] = provider

    def list_providers(self) -> List[str]:
        """列出支持的provider"""
        return list(self.ADAPTER_MAP.keys())
