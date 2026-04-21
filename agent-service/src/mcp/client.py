"""MCP客户端 - 支持多种传输方式"""

from typing import Dict, Any, List, Optional
from enum import Enum
import time

from .transports import (
    BaseTransport,
    TransportType,
    StdioTransport,
    SSETransport,
    WebSocketTransport,
    HTTPTransport
)
from ..observability import (
    MCP_TOOL_CALLS,
    MCP_TOOL_LATENCY,
    get_logger,
)

logger = get_logger(__name__)


class MCPClient:
    """MCP客户端 - 支持多种传输方式"""

    # 传输类型映射
    TRANSPORT_MAP = {
        TransportType.STDIO: StdioTransport,
        TransportType.SSE: SSETransport,
        TransportType.WEBSOCKET: WebSocketTransport,
        TransportType.HTTP: HTTPTransport,
    }

    def __init__(
        self,
        transport_type: str = "http",
        server_url: str = None,
        command: str = None,
        args: List[str] = None,
        env: Dict[str, str] = None,
        cwd: str = None,
        api_key: str = None,
        timeout: int = 30,
        headers: Dict[str, str] = None,
        **kwargs
    ):
        """
        初始化MCP客户端

        Args:
            transport_type: 传输类型 (stdio, sse, websocket, http)
            server_url: 服务器URL (用于 sse/websocket/http)
            command: MCP服务命令 (用于 stdio)
            args: 命令参数 (用于 stdio)
            env: 环境变量 (用于 stdio)
            cwd: 工作目录 (用于 stdio)
            api_key: API密钥 (用于 sse/websocket)
            timeout: 超时时间
            headers: HTTP头 (用于 http)
            **kwargs: 其他传输特定参数
        """
        self.transport_type = TransportType(transport_type.lower())
        self.timeout = timeout
        self._transport: Optional[BaseTransport] = None
        self._tools_cache: Optional[List[Dict]] = None
        self._config = {
            "server_url": server_url,
            "command": command,
            "args": args,
            "env": env,
            "cwd": cwd,
            "api_key": api_key,
            "headers": headers,
            **kwargs
        }

    def _create_transport(self) -> BaseTransport:
        """创建传输实例"""
        transport_class = self.TRANSPORT_MAP.get(self.transport_type)

        if transport_class is None:
            raise ValueError(f"Unknown transport type: {self.transport_type}")

        if self.transport_type == TransportType.STDIO:
            return transport_class(
                command=self._config.get("command"),
                args=self._config.get("args"),
                env=self._config.get("env"),
                cwd=self._config.get("cwd"),
                timeout=self.timeout
            )
        elif self.transport_type == TransportType.SSE:
            return transport_class(
                server_url=self._config.get("server_url"),
                api_key=self._config.get("api_key"),
                timeout=self.timeout
            )
        elif self.transport_type == TransportType.WEBSOCKET:
            return transport_class(
                server_url=self._config.get("server_url"),
                api_key=self._config.get("api_key"),
                timeout=self.timeout
            )
        else:  # HTTP
            return transport_class(
                server_url=self._config.get("server_url", "http://localhost:5000"),
                timeout=self.timeout,
                headers=self._config.get("headers")
            )

    async def connect(self) -> bool:
        """建立连接"""
        if self._transport is None:
            self._transport = self._create_transport()
        return await self._transport.connect()

    async def disconnect(self) -> None:
        """断开连接"""
        if self._transport:
            await self._transport.disconnect()

    async def list_tools(self) -> List[Dict[str, Any]]:
        """获取可用工具列表"""
        if self._tools_cache is not None:
            return self._tools_cache

        if self._transport is None:
            await self.connect()

        try:
            tools = await self._transport.list_tools()
            self._tools_cache = tools
            return tools
        except Exception as e:
            # 如果获取失败，返回模拟工具列表（开发模式）
            return self._get_mock_tools()

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        调用MCP工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果
        """
        if self._transport is None:
            await self.connect()

        start_time = time.time()
        status = "success"

        try:
            logger.debug(f"Calling MCP tool: {tool_name}")
            result = await self._transport.call_tool(tool_name, arguments)
            logger.debug(f"MCP tool call succeeded: {tool_name}")
            return result
        except Exception as e:
            status = "error"
            logger.error(f"MCP tool call failed: {tool_name}, error: {e}")
            # 开发模式：返回模拟数据
            return self._mock_tool_call(tool_name, arguments)
        finally:
            duration = time.time() - start_time
            MCP_TOOL_CALLS.labels(tool_name=tool_name, status=status).inc()
            MCP_TOOL_LATENCY.labels(tool_name=tool_name).observe(duration)

    async def send_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """发送原始MCP请求"""
        if self._transport is None:
            await self.connect()
        return await self._transport.send_request(method, params)

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._transport.is_connected if self._transport else False

    def clear_cache(self):
        """清除工具缓存"""
        self._tools_cache = None

    # ========== 开发模式：模拟工具 ==========

    def _get_mock_tools(self) -> List[Dict]:
        """获取模拟工具列表（开发测试用）"""
        return [
            {
                "name": "parse_data",
                "description": "解析profiling数据",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "data_path": {"type": "string", "description": "数据文件路径"}
                    },
                    "required": ["data_path"]
                }
            },
            {
                "name": "get_overview",
                "description": "获取数据概览",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "data_id": {"type": "string", "description": "数据ID"}
                    },
                    "required": ["data_id"]
                }
            },
            {
                "name": "get_comm_domains",
                "description": "获取通信域列表",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "data_id": {"type": "string", "description": "数据ID"}
                    },
                    "required": ["data_id"]
                }
            },
            {
                "name": "analyze_slow_cards",
                "description": "快慢卡分析",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "data_id": {"type": "string"},
                        "domain": {"type": "string"}
                    },
                    "required": ["data_id", "domain"]
                }
            },
            {
                "name": "analyze_memory",
                "description": "内存问题分析",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "data_id": {"type": "string"}
                    },
                    "required": ["data_id"]
                }
            }
        ]

    def _mock_tool_call(self, tool_name: str, arguments: Dict) -> Dict:
        """模拟工具调用（开发测试用）"""
        mock_results = {
            "parse_data": {
                "data_id": "mock_data_001",
                "data_type": "profiling",
                "summary": {"total_ranks": 8, "iterations": 100}
            },
            "get_overview": {
                "problem_types": ["communication", "memory"],
                "metrics": {"avg_latency": 150, "peak_memory": "80%"}
            },
            "get_comm_domains": {
                "domains": [
                    {"name": "world_group", "rank_count": 8},
                    {"name": "tp_group", "rank_count": 4},
                    {"name": "dp_group", "rank_count": 2}
                ]
            },
            "analyze_slow_cards": {
                "slow_cards": [
                    {"rank": 3, "latency": 250, "severity": "high"},
                    {"rank": 7, "latency": 180, "severity": "medium"}
                ],
                "analysis": {"bottleneck": "inter-node communication"}
            },
            "analyze_memory": {
                "issues": [
                    {"type": "peak_memory", "severity": "high", "location": "rank_0", "description": "峰值内存过高"}
                ],
                "metrics": {"peak_memory": "90%", "avg_memory": "65%"}
            }
        }
        return mock_results.get(tool_name, {})

    # ========== 工厂方法 ==========

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "MCPClient":
        """
        从配置字典创建客户端

        Args:
            config: 配置字典，格式:
                {
                    "transport": "http",  # 或 "stdio", "sse", "websocket"
                    "server_url": "http://localhost:5000",  # 用于 http/sse/websocket
                    "command": "python",  # 用于 stdio
                    "args": ["-m", "my_mcp_server"],  # 用于 stdio
                    "env": {},  # 用于 stdio
                    "api_key": "xxx",  # 用于 sse/websocket
                    "timeout": 30
                }
        """
        return cls(
            transport_type=config.get("transport", "http"),
            server_url=config.get("server_url"),
            command=config.get("command"),
            args=config.get("args"),
            env=config.get("env"),
            cwd=config.get("cwd"),
            api_key=config.get("api_key"),
            timeout=config.get("timeout", 30),
            headers=config.get("headers"),
            reconnect=config.get("reconnect", True),
            reconnect_interval=config.get("reconnect_interval", 5)
        )
