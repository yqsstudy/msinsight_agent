"""HTTP传输实现 - 兼容现有方式"""

import json
from typing import Dict, Any, List, Optional
import httpx

from .base import BaseTransport


class HTTPTransport(BaseTransport):
    """HTTP REST传输"""

    def __init__(self, server_url: str, timeout: int = 30, headers: Dict[str, str] = None):
        super().__init__(timeout)
        self.server_url = server_url.rstrip("/")
        self.headers = headers or {}
        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False

    async def connect(self) -> bool:
        """建立连接"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers=self.headers
            )
        self._connected = True
        return True

    async def disconnect(self) -> None:
        """断开连接"""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False

    async def send_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """发送HTTP请求"""
        if not self._client:
            await self.connect()

        # 将MCP方法映射到HTTP端点
        endpoint = f"/{method.replace('/', '_')}"
        url = f"{self.server_url}{endpoint}"

        try:
            response = await self._client.post(url, json=params or {})
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise ConnectionError(f"HTTP request failed: {e}")

    async def list_tools(self) -> List[Dict[str, Any]]:
        """获取工具列表"""
        try:
            response = await self._client.post(f"{self.server_url}/tools/list")
            response.raise_for_status()
            data = response.json()
            return data.get("tools", [])
        except Exception:
            return []

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """调用工具"""
        response = await self._client.post(
            f"{self.server_url}/tools/call",
            json={"name": tool_name, "arguments": arguments}
        )
        response.raise_for_status()
        data = response.json()
        return data.get("content", [{}])[0].get("text", {})

    @property
    def is_connected(self) -> bool:
        return self._connected
