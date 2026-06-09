"""SDK-backed stdio transport for MCP servers."""

import asyncio
import importlib
import os
import site
import sys
import types
import json
import time
from typing import Any, Dict, List, Optional

from ...observability import get_logger
from .base import BaseTransport

logger = get_logger(__name__)


class StdioTransport(BaseTransport):
    """Stdio transport backed by the official MCP Python SDK."""

    def __init__(
        self,
        command: str,
        args: List[str] = None,
        env: Dict[str, str] = None,
        cwd: str = None,
        timeout: int = 30,
    ):
        super().__init__(timeout)
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd
        self._request_id = 0
        self._session: Optional[Any] = None
        self._connected = False
        self.last_trace: Optional[Dict[str, Any]] = None
        self._bg_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._init_future: Optional[asyncio.Future] = None

    async def _run_session(self):
        command_display = " ".join([str(self.command), *[str(arg) for arg in self.args]])
        try:
            ClientSession, StdioServerParameters, stdio_client = self._load_sdk()
            server_params = StdioServerParameters(
                command=self.command,
                args=self.args,
                env=self.env or None,
                cwd=self.cwd,
            )
            logger.info(f"Starting MCP stdio SDK session: command={command_display}, cwd={self.cwd}")
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    self._session = session
                    self._connected = True
                    self._init_future.set_result(True)
                    
                    # Keep session alive
                    await self._stop_event.wait()
                    
        except Exception as exc:
            logger.exception(f"MCP SDK session error: command={command_display}, cwd={self.cwd}, error={exc}")
            if not self._init_future.done():
                self._init_future.set_exception(exc)
        finally:
            self._connected = False
            self._session = None

    async def connect(self) -> bool:
        """Start the MCP server and initialize an SDK client session."""
        if self._connected and self._session is not None:
            return True
            
        if self._bg_task is not None:
            await asyncio.wait_for(self._init_future, timeout=self.timeout)
            return True

        self._stop_event = asyncio.Event()
        self._init_future = asyncio.Future()
        self._bg_task = asyncio.create_task(self._run_session())
        
        try:
            await asyncio.wait_for(self._init_future, timeout=self.timeout)
            return True
        except Exception as exc:
            await self.disconnect()
            raise ConnectionError(f"Failed to start MCP process: {exc}") from exc

    async def disconnect(self) -> None:
        """Close SDK session and stop the MCP server process."""
        # Compatibility with older direct context-manager based tests/callers.
        session_cm = getattr(self, "_session_cm", None)
        stdio_cm = getattr(self, "_stdio_cm", None)
        if self._bg_task is None:
            if session_cm is not None:
                await session_cm.__aexit__(None, None, None)
            if stdio_cm is not None:
                await stdio_cm.__aexit__(None, None, None)

        if self._stop_event:
            self._stop_event.set()

        if self._bg_task:
            try:
                await asyncio.wait_for(self._bg_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._bg_task.cancel()
            except Exception:
                pass
                
        self._bg_task = None
        self._stop_event = None
        self._init_future = None
        self._session = None
        self._connected = False

    async def send_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Compatibility shim for existing callers; prefer typed SDK methods."""
        if method == "tools/list":
            return {"tools": await self.list_tools()}

        if method == "tools/call":
            if not isinstance(params, dict) or not params.get("name"):
                raise ValueError("tools/call requires params.name")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise ValueError("tools/call params.arguments must be an object")
            return await self.call_tool(str(params["name"]), arguments)

        raise NotImplementedError(f"Raw MCP method is not supported by SDK-backed stdio transport: {method}")

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List MCP tools through the SDK session."""
        await self._ensure_connected()
        started_at = time.time()
        request = self._request("tools/list")
        self.last_trace = self._build_trace(request=request, status="running", started_at=started_at)
        try:
            response = await asyncio.wait_for(self._session.list_tools(), timeout=self.timeout)
            tools = [self._normalize_tool(tool) for tool in getattr(response, "tools", [])]
            payload = {"tools": tools}
            self.last_trace = self._build_trace(request=request, response=payload, status="success", started_at=started_at)
            logger.info(f"MCP tools loaded via SDK stdio: count={len(tools)}")
            return tools
        except Exception as exc:
            self.last_trace = self._build_trace(request=request, status="error", started_at=started_at, error=f"{type(exc).__name__}: {exc!r}")
            raise

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call an MCP tool through the SDK session."""
        await self._ensure_connected()
        started_at = time.time()
        request = self._request("tools/call", {"name": tool_name, "arguments": arguments})
        self.last_trace = self._build_trace(request=request, status="running", started_at=started_at)
        try:
            response = await asyncio.wait_for(self._session.call_tool(tool_name, arguments), timeout=self.timeout)
            result = self._normalize_call_result(response)
            self.last_trace = self._build_trace(request=request, response=result, status="success", started_at=started_at)
            if isinstance(result, dict):
                return {**result, "_mcp_trace": self.last_trace}
            return {"value": result, "_mcp_trace": self.last_trace}
        except Exception as exc:
            self.last_trace = self._build_trace(request=request, status="error", started_at=started_at, error=f"{type(exc).__name__}: {exc!r}")
            raise

    async def _ensure_connected(self) -> None:
        if not self.is_connected:
            await self.connect()

    def _load_sdk(self):
        local_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        sdk_package_dir = self._find_sdk_package_dir(local_src)
        if not sdk_package_dir:
            raise ModuleNotFoundError("Official MCP SDK package directory was not found outside project src")

        previous_mcp = sys.modules.get("mcp")
        if previous_mcp is not None and not getattr(previous_mcp, "_msinsight_sdk_shell", False):
            sys.modules.pop("mcp", None)

        package = sys.modules.get("mcp")
        if package is None:
            package = types.ModuleType("mcp")
            package.__path__ = [sdk_package_dir]
            package.__package__ = "mcp"
            package.__file__ = os.path.join(sdk_package_dir, "__init__.py")
            package._msinsight_sdk_shell = True
            sys.modules["mcp"] = package

        session = importlib.import_module("mcp.client.session")
        stdio = importlib.import_module("mcp.client.stdio")
        return session.ClientSession, stdio.StdioServerParameters, stdio.stdio_client

    def _find_sdk_package_dir(self, local_src: str) -> Optional[str]:
        candidates = []
        for path in [*site.getsitepackages(), site.getusersitepackages(), *sys.path]:
            if not path:
                continue
            candidate = os.path.abspath(os.path.join(path, "mcp"))
            if candidate in candidates:
                continue
            candidates.append(candidate)

        for candidate in candidates:
            if not os.path.isdir(candidate):
                continue
            if candidate.startswith(local_src):
                continue
            if os.path.exists(os.path.join(candidate, "client", "session.py")) and os.path.exists(os.path.join(candidate, "client", "stdio", "__init__.py")):
                return candidate
        return None

    def _module_matches_path(self, module: Any, package_dir: str) -> bool:
        module_file = getattr(module, "__file__", "")
        module_paths = getattr(module, "__path__", [])
        if module_file and os.path.abspath(str(module_file)).startswith(package_dir):
            return True
        return any(os.path.abspath(str(path)).startswith(package_dir) for path in module_paths)

    def _request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._request_id += 1
        request = {
            "id": self._request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params
        return request

    def _build_trace(
        self,
        request: Dict[str, Any],
        status: str,
        started_at: float,
        response: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = request.get("params") or {}
        return {
            "transport": "stdio",
            "request_id": request.get("id"),
            "method": request.get("method"),
            "tool_name": params.get("name"),
            "elapsed_ms": int((time.time() - started_at) * 1000),
            "status": status,
            "request": request,
            "response": self._truncate(response),
            "error": error,
        }

    def _normalize_tool(self, tool: Any) -> Dict[str, Any]:
        data = self._to_dict(tool)
        if "inputSchema" not in data and "input_schema" in data:
            data["inputSchema"] = data.pop("input_schema")
        return data

    def _normalize_call_result(self, response: Any) -> Dict[str, Any]:
        data = self._to_dict(response)
        if "structured_content" in data and "structuredContent" not in data:
            data["structuredContent"] = data["structured_content"]
        if "is_error" in data and "isError" not in data:
            data["isError"] = data["is_error"]

        if data.get("isError"):
            raise RuntimeError(self._extract_error_text(data))

        parsed_text = self._parse_single_text_json(data.get("content"))
        if isinstance(parsed_text, dict):
            data.setdefault("parsedContent", parsed_text)
        return data

    def _to_dict(self, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return {key: self._normalize_json_value(item) for key, item in value.items()}
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json", by_alias=True, exclude_none=True)
        if hasattr(value, "dict"):
            return value.dict(by_alias=True, exclude_none=True)
        result: Dict[str, Any] = {}
        for field in ("name", "description", "inputSchema", "input_schema", "content", "structuredContent", "structured_content", "isError", "is_error"):
            if hasattr(value, field):
                result[field] = self._normalize_json_value(getattr(value, field))
        return result

    def _normalize_json_value(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._normalize_json_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._normalize_json_value(item) for key, item in value.items()}
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json", by_alias=True, exclude_none=True)
        if hasattr(value, "dict"):
            return value.dict(by_alias=True, exclude_none=True)
        if any(hasattr(value, field) for field in ("text", "type", "data", "mimeType", "uri")):
            return {
                field: self._normalize_json_value(getattr(value, field))
                for field in ("text", "type", "data", "mimeType", "uri")
                if hasattr(value, field)
            }
        return value

    def _parse_single_text_json(self, content: Any) -> Optional[Any]:
        if not isinstance(content, list) or len(content) != 1:
            return None
        item = content[0]
        item_data = self._to_dict(item) if not isinstance(item, dict) else item
        text = item_data.get("text")
        if not isinstance(text, str):
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _extract_error_text(self, data: Dict[str, Any]) -> str:
        content = data.get("content")
        if isinstance(content, list):
            parts = []
            for item in content:
                item_data = self._to_dict(item) if not isinstance(item, dict) else item
                parts.append(str(item_data.get("text", item_data)))
            if parts:
                return "\n".join(parts)
        return str(data)

    def _truncate(self, value: Any) -> Any:
        if value is None:
            return None
        text = str(value)
        if len(text) <= 20000:
            return value
        return {"preview": text[:20000], "truncated": True}

    @property
    def is_connected(self) -> bool:
        return self._connected and self._session is not None
