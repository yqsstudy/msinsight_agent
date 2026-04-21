"""MCP传输层抽象基类"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from enum import Enum


class TransportType(Enum):
    """传输类型"""
    STDIO = "stdio"
    SSE = "sse"
    WEBSOCKET = "websocket"
    HTTP = "http"  # 兼容现有的HTTP方式


class BaseTransport(ABC):
    """MCP传输层基类"""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    @abstractmethod
    async def connect(self) -> bool:
        """建立连接"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        pass

    @abstractmethod
    async def send_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        发送请求

        Args:
            method: MCP方法名 (如 tools/list, tools/call)
            params: 参数

        Returns:
            响应结果
        """
        pass

    @abstractmethod
    async def list_tools(self) -> List[Dict[str, Any]]:
        """获取工具列表"""
        pass

    @abstractmethod
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """调用工具"""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """是否已连接"""
        pass
