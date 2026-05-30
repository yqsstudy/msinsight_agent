"""测试MCP多传输方式"""

import pytest
import asyncio
import sys
from types import SimpleNamespace
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

        tools = await client.list_tools()
        assert isinstance(tools, list)

    @pytest.mark.asyncio
    async def test_call_tool_uses_transport(self):
        """测试工具调用委托给transport"""
        client = MCPClient(
            transport_type="http",
            server_url="http://localhost:5000"
        )
        client._transport = AsyncMock()
        client._transport.call_tool.return_value = {"data_id": "transport_result_001"}

        result = await client.call_tool("parse_data", {"data_path": "/test/path"})

        client._transport.call_tool.assert_awaited_once_with("parse_data", {"data_path": "/test/path"})
        assert result["data_id"] == "transport_result_001"


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


    def test_load_sdk_replaces_broken_top_level_mcp(self):
        """测试加载SDK时不复用已损坏的顶层mcp模块"""
        transport = StdioTransport(command="python")
        broken_mcp = SimpleNamespace(__file__="D:/broken/mcp/__init__.py")
        sys.modules["mcp"] = broken_mcp
        try:
            with patch.object(transport, "_find_sdk_package_dir", return_value="D:/sdk/site-packages/mcp"), \
                 patch("src.mcp.transports.stdio_transport.importlib.import_module") as import_module:
                session_module = SimpleNamespace(ClientSession=object)
                stdio_module = SimpleNamespace(StdioServerParameters=object, stdio_client=object())
                import_module.side_effect = [session_module, stdio_module]

                loaded = transport._load_sdk()

            assert loaded == (object, object, stdio_module.stdio_client)
            assert getattr(sys.modules["mcp"], "_msinsight_sdk_shell") is True
            assert sys.modules["mcp"].__path__ == ["D:/sdk/site-packages/mcp"]
        finally:
            sys.modules.pop("mcp", None)

    @pytest.mark.asyncio
    async def test_sdk_connect_initializes_session(self):
        """测试Stdio通过官方SDK初始化会话"""
        transport = StdioTransport(command="python", args=["-m", "test"])
        stdio_cm = AsyncMock()
        session_cm = AsyncMock()
        session = AsyncMock()
        stdio_cm.__aenter__.return_value = ("read", "write")
        session_cm.__aenter__.return_value = session

        with patch.object(transport, "_load_sdk", return_value=(Mock(return_value=session_cm), Mock(), Mock(return_value=stdio_cm))):
            connected = await transport.connect()

        assert connected
        assert transport.is_connected
        session.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sdk_list_tools_normalizes_models(self):
        """测试Stdio通过SDK列出工具并归一化字段"""
        transport = StdioTransport(command="python")
        session = AsyncMock()
        session.list_tools.return_value = SimpleNamespace(
            tools=[SimpleNamespace(name="search_profiler_tools", description="search", input_schema={"type": "object"})]
        )
        transport._session = session
        transport._connected = True

        tools = await transport.list_tools()

        assert tools == [{"name": "search_profiler_tools", "description": "search", "inputSchema": {"type": "object"}}]
        assert transport.last_trace["method"] == "tools/list"
        assert transport.last_trace["status"] == "success"

    @pytest.mark.asyncio
    async def test_sdk_call_tool_returns_trace(self):
        """测试Stdio通过SDK调用工具并返回trace"""
        transport = StdioTransport(command="python")
        session = AsyncMock()
        session.call_tool.return_value = SimpleNamespace(content=[SimpleNamespace(text="ok")], is_error=False)
        transport._session = session
        transport._connected = True

        result = await transport.call_tool("search_profiler_tools", {"query": "slow card"})

        session.call_tool.assert_awaited_once_with("search_profiler_tools", {"query": "slow card"})
        assert result["content"][0]["text"] == "ok"
        assert result["_mcp_trace"]["method"] == "tools/call"
        assert result["_mcp_trace"]["tool_name"] == "search_profiler_tools"

    @pytest.mark.asyncio
    async def test_send_request_compat_tools_list(self):
        """测试send_request兼容tools/list"""
        transport = StdioTransport(command="python")
        with patch.object(transport, "list_tools", AsyncMock(return_value=[{"name": "tool"}])):
            result = await transport.send_request("tools/list")

        assert result == {"tools": [{"name": "tool"}]}

    @pytest.mark.asyncio
    async def test_send_request_rejects_unknown_raw_method(self):
        """测试SDK-backed Stdio拒绝未知raw请求"""
        transport = StdioTransport(command="python")
        with pytest.raises(NotImplementedError):
            await transport.send_request("resources/list")

    @pytest.mark.asyncio
    async def test_disconnect_exits_sdk_contexts(self):
        """测试断开连接时退出SDK上下文"""
        transport = StdioTransport(command="python")
        transport._connected = True
        transport._session = AsyncMock()
        transport._session_cm = AsyncMock()
        transport._stdio_cm = AsyncMock()
        session_cm = transport._session_cm
        stdio_cm = transport._stdio_cm

        await transport.disconnect()

        session_cm.__aexit__.assert_awaited_once_with(None, None, None)
        stdio_cm.__aexit__.assert_awaited_once_with(None, None, None)
        assert not transport.is_connected


class TestWebSocketTransport:

    def test_url_conversion(self):
        """测试URL转换"""
        transport = WebSocketTransport(server_url="http://localhost:5000")
        assert transport.server_url == "ws://localhost:5000"

        transport = WebSocketTransport(server_url="https://localhost:5000")
        assert transport.server_url == "wss://localhost:5000"
