"""Stdio传输实现 - 通过标准输入输出与MCP服务进程通信"""

import asyncio
import json
import os
from typing import Dict, Any, List, Optional
import sys

from .base import BaseTransport


class StdioTransport(BaseTransport):
    """Stdio传输 - 启动MCP服务进程并通过stdin/stdout通信"""

    def __init__(
        self,
        command: str,
        args: List[str] = None,
        env: Dict[str, str] = None,
        cwd: str = None,
        timeout: int = 30
    ):
        super().__init__(timeout)
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd
        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._request_id = 0

    async def connect(self) -> bool:
        """启动MCP服务进程"""
        if self._process is not None:
            return True

        # 合并环境变量
        process_env = os.environ.copy()
        process_env.update(self.env)

        try:
            self._process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env,
                cwd=self.cwd
            )
            return True
        except Exception as e:
            raise ConnectionError(f"Failed to start MCP process: {e}")

    async def disconnect(self) -> None:
        """终止MCP进程"""
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            finally:
                self._process = None

    async def send_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """发送JSON-RPC请求"""
        if not self._process:
            await self.connect()

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {}
        }

        # 发送请求
        request_line = json.dumps(request) + "\n"
        self._process.stdin.write(request_line.encode())
        await self._process.stdin.drain()

        # 读取响应
        response_line = await asyncio.wait_for(
            self._process.stdout.readline(),
            timeout=self.timeout
        )
        response = json.loads(response_line.decode())

        if "error" in response:
            raise RuntimeError(f"MCP error: {response['error']}")

        return response.get("result", {})

    async def list_tools(self) -> List[Dict[str, Any]]:
        """获取工具列表"""
        result = await self.send_request("tools/list")
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """调用工具"""
        result = await self.send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
        return result

    @property
    def is_connected(self) -> bool:
        return self._process is not None and self._process.returncode is None
