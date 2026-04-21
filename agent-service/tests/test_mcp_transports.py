"""测试MCP多传输方式"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from src.mcp import MCPClient, TransportType
from src.mcp.transports import (
    HTTPTransport,
    StdioTransport,
    SSETransport,
    WebSocketTransport
)


class TestMCPClient:

    def test_create_http_transport(self):
        """测试创建HTTP传输"""
        client = MCPClient(
            transport_type="http",
            server_url="http://localhost:5000"
        )
        assert client.transport_type == TransportType.HTTP

    def test_create_stdio_transport(self):
        """测试创建Stdio传输"""
        client = MCPClient(
            transport_type="stdio",
            command="python",
            args=["-m", "my_mcp_server"]
        )
        assert client.transport_type == TransportType.STDIO

    def test_create_sse_transport(self):
        """测试创建SSE传输"""
        client = MCPClient(
            transport_type="sse",
            server_url="http://localhost:5000",
            api_key="test-key"
        )
        assert client.transport_type == TransportType.SSE

    def test_create_websocket_transport(self):
        """测试创建WebSocket传输"""
        client = MCPClient(
            transport_type="websocket",
            server_url="ws://localhost:5000"
        )
        assert client.transport_type == TransportType.WEBSOCKET

    def test_from_config(self):
        """测试从配置创建客户端"""
        config = {
            "transport": "http",
            "server_url": "http://localhost:5000",
            "timeout": 30
        }
        client = MCPClient.from_config(config)
        assert client.transport_type == TransportType.HTTP

    def test_from_config_stdio(self):
        """测试从配置创建Stdio客户端"""
        config = {
            "transport": "stdio",
            "command": "python",
            "args": ["-m", "mcp_server"],
            "env": {"DEBUG": "1"}
        }
        client = MCPClient.from_config(config)
        assert client.transport_type == TransportType.STDIO

    @pytest.mark.asyncio
    async def test_http_list_tools(self):
        """测试HTTP获取工具列表"""
        client = MCPClient(
            transport_type="http",
            server_url="http://localhost:5000"
        )

        # 开发模式下会返回模拟工具
        tools = await client.list_tools()
        assert isinstance(tools, list)

    @pytest.mark.asyncio
    async def test_call_tool_mock(self):
        """测试模拟工具调用"""
        client = MCPClient(
            transport_type="http",
            server_url="http://localhost:5000"
        )

        # 开发模式下会返回模拟数据
        result = await client.call_tool("parse_data", {"data_path": "/test/path"})
        assert "data_id" in result


class TestHTTPTransport:

    @pytest.mark.asyncio
    async def test_connect(self):
        """测试HTTP连接"""
        transport = HTTPTransport(server_url="http://localhost:5000")
        connected = await transport.connect()
        assert connected
        assert transport.is_connected

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """测试断开连接"""
        transport = HTTPTransport(server_url="http://localhost:5000")
        await transport.connect()
        await transport.disconnect()
        assert not transport.is_connected


class TestStdioTransport:

    def test_init(self):
        """测试Stdio初始化"""
        transport = StdioTransport(
            command="python",
            args=["-m", "test"],
            env={"TEST": "1"}
        )
        assert transport.command == "python"
        assert transport.args == ["-m", "test"]
        assert transport.env == {"TEST": "1"}


class TestWebSocketTransport:

    def test_url_conversion(self):
        """测试URL转换"""
        transport = WebSocketTransport(server_url="http://localhost:5000")
        assert transport.server_url == "ws://localhost:5000"

        transport = WebSocketTransport(server_url="https://localhost:5000")
        assert transport.server_url == "wss://localhost:5000"
