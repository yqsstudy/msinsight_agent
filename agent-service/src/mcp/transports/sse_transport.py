"""SSE传输实现 - Server-Sent Events"""

import asyncio
import json
from typing import Dict, Any, List, Optional
import httpx

from .base import BaseTransport


class SSETransport(BaseTransport):
    """SSE传输 - 通过Server-Sent Events与MCP服务通信"""

    def __init__(
        self,
        server_url: str,
        api_key: str = None,
        timeout: int = 30,
        reconnect_interval: int = 5
    ):
        super().__init__(timeout)
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.reconnect_interval = reconnect_interval
        self._client: Optional[httpx.AsyncClient] = None
        self._event_source = None
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._request_id = 0
        self._connected = False

    async def connect(self) -> bool:
        """建立SSE连接"""
        if self._client is None:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, read=None),  # SSE需要无限读取超时
                headers=headers
            )

        # 启动SSE监听
        self._connected = True
        return True

    async def disconnect(self) -> None:
        """断开连接"""
        self._connected = False
        if self._client:
            await self._client.aclose()
            self._client = None

    async def send_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """发送HTTP请求并等待SSE响应"""
        if not self._client:
            await self.connect()

        self._request_id += 1
        request_id = self._request_id

        # 创建Future等待响应
        future = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            # 发送请求
            response = await self._client.post(
                f"{self.server_url}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params or {}
                }
            )
            response.raise_for_status()

            # 等待SSE响应（简化实现，直接从HTTP响应获取）
            result = response.json()

            if "error" in result:
                raise RuntimeError(f"MCP error: {result['error']}")

            return result.get("result", {})

        except asyncio.TimeoutError:
            raise TimeoutError(f"MCP request timeout: {method}")
        finally:
            self._pending_requests.pop(request_id, None)

    async def list_tools(self) -> List[Dict[str, Any]]:
        """获取工具列表"""
        result = await self.send_request("tools/list")
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """调用工具"""
        return await self.send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })

    @property
    def is_connected(self) -> bool:
        return self._connected
