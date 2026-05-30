"""WebSocket传输实现"""

import asyncio
import json
from typing import Dict, Any, List, Optional
import websockets

from .base import BaseTransport


class WebSocketTransport(BaseTransport):
    """WebSocket传输 - 通过WebSocket与MCP服务通信"""

    def __init__(
        self,
        server_url: str,
        api_key: str = None,
        timeout: int = 30,
        reconnect: bool = True,
        reconnect_interval: int = 5
    ):
        super().__init__(timeout)
        # 确保URL使用ws/wss协议
        if server_url.startswith("http://"):
            server_url = "ws://" + server_url[7:]
        elif server_url.startswith("https://"):
            server_url = "wss://" + server_url[8:]

        self.server_url = server_url
        self.api_key = api_key
        self.reconnect = reconnect
        self.reconnect_interval = reconnect_interval
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._receive_task: Optional[asyncio.Task] = None
        self._connected = False

    async def connect(self) -> bool:
        """建立WebSocket连接"""
        if self._ws is not None:
            return True

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            self._ws = await websockets.connect(
                self.server_url,
                additional_headers=headers,
                ping_interval=30,
                ping_timeout=10
            )
            self._connected = True

            # 启动接收任务
            self._receive_task = asyncio.create_task(self._receive_loop())

            return True
        except Exception as e:
            raise ConnectionError(f"WebSocket connection failed: {e}")

    async def disconnect(self) -> None:
        """断开连接"""
        self._connected = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        # 取消所有待处理请求
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()

    async def _receive_loop(self):
        """接收消息循环"""
        try:
            async for message in self._ws:
                try:
                    data = json.loads(message)
                    request_id = data.get("id")

                    if request_id and request_id in self._pending_requests:
                        future = self._pending_requests.pop(request_id)
                        if not future.done():
                            if "error" in data:
                                future.set_exception(RuntimeError(data["error"]))
                            else:
                                future.set_result(data.get("result", {}))
                except json.JSONDecodeError:
                    continue
        except websockets.ConnectionClosed:
            self._connected = False
            if self.reconnect:
                await self._try_reconnect()
        except asyncio.CancelledError:
            pass

    async def _try_reconnect(self):
        """尝试重连"""
        while self.reconnect and not self._connected:
            try:
                await self.connect()
                if self._connected:
                    break
            except Exception:
                pass
            await asyncio.sleep(self.reconnect_interval)

    async def send_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """发送请求"""
        if not self._ws:
            await self.connect()

        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        # 创建Future等待响应
        future = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            await self._ws.send(json.dumps(request))

            # 等待响应
            result = await asyncio.wait_for(future, timeout=self.timeout)
            return result

        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise TimeoutError(f"MCP request timeout: {method}")

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
        return self._connected and self._ws is not None
