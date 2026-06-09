"""MCP meta-tool gateway adapter."""

import json
import time
from typing import Any, Dict, Optional

from ..mcp.client import MCPClient
from ..models.config import MCPHarnessConfig
from ..models.orchestration import MCPSearchResult, MCPToolResult
from ..observability import get_logger
from .mcp_response_parser import MCPResponseParser

logger = get_logger(__name__)


class MCPGateway:
    """Adapter exposing only MSInsight MCP meta tools."""

    def __init__(self, config: Optional[MCPHarnessConfig] = None, client: Optional[MCPClient] = None):
        self.config = config or MCPHarnessConfig()
        self.client = client or MCPClient.from_config(self.config.to_mcp_client_config())
        self.parser = MCPResponseParser()
        self.tools_cache: list[Dict[str, Any]] = []
        self.tools_by_name: Dict[str, Dict[str, Any]] = {}
        self.missing_required_tools: list[str] = []
        self.last_tools_list_trace: Optional[Dict[str, Any]] = None

    async def ensure_tools_loaded(self, force: bool = False) -> list[Dict[str, Any]]:
        if self.tools_cache and not force:
            return self.tools_cache
        tools = await self.client.list_tools()
        self.tools_cache = tools
        self.tools_by_name = {str(tool.get("name")): tool for tool in tools if tool.get("name")}
        self.missing_required_tools = [name for name in self.config.required_meta_tools if name not in self.tools_by_name]
        self.last_tools_list_trace = self._last_trace()
        tool_names = list(self.tools_by_name.keys())
        logger.info(f"MCP tools loaded: count={len(tool_names)}, tools={tool_names}, missing_required={self.missing_required_tools}")
        if self.missing_required_tools:
            raise RuntimeError(f"Missing required MCP meta tools: {self.missing_required_tools}; available={tool_names}")
        return self.tools_cache

    def _require_tool(self, tool_name: str) -> None:
        if self.tools_by_name and tool_name not in self.tools_by_name:
            raise RuntimeError(f"MCP tool not found: {tool_name}; available={list(self.tools_by_name.keys())}")

    async def search_profiler_tools(
        self,
        query: str,
        select_playbook: Optional[str] = None,
    ) -> MCPSearchResult:
        start = time.time()
        arguments: Dict[str, Any] = {"query": query}
        if select_playbook:
            arguments["select_playbook"] = select_playbook
        try:
            await self.ensure_tools_loaded()
            self._require_tool("search_profiler_tools")
            raw = await self.client.call_tool("search_profiler_tools", arguments)
        except Exception as exc:
            trace = self._last_trace()
            logger.error(f"MCP search_profiler_tools failed: {exc}; trace={trace}")
            raise RuntimeError(f"MCP_UNAVAILABLE: {exc}; trace={trace}") from exc

        elapsed_ms = int((time.time() - start) * 1000)
        text = self._extract_text(raw)
        safe_raw = self._safe_raw(raw)
        structured = self._structured_payload(safe_raw)
        selected_playbook = self.parser.parse_selected_playbook(structured, text)
        initial_step = self.parser.parse_initial_step(structured, text)
        candidates = self.parser.parse_candidates(structured, text)
        suggested_arguments = self.parser.parse_suggested_arguments(structured)
        requires_choice = bool(candidates) and not selected_playbook
        if "请选择" in text and not selected_playbook:
            requires_choice = True
        return MCPSearchResult(
            status="completed",
            text=text,
            playbook_candidates=candidates,
            auto_selected_playbook=selected_playbook,
            selected_playbook=selected_playbook,
            initial_step=initial_step,
            suggested_arguments=suggested_arguments,
            requires_user_choice=requires_choice,
            elapsed_ms=elapsed_ms,
            raw=safe_raw,
        )

    async def execute_profiler_tool(self, tool_name: str, arguments: Dict[str, Any]) -> MCPToolResult:
        start = time.time()
        try:
            await self.ensure_tools_loaded()
            self._require_tool("execute_profiler_tool")
            raw = await self.client.call_tool(
                "execute_profiler_tool",
                {"tool_name": tool_name, "arguments": arguments},
            )
        except Exception as exc:
            trace = self._last_trace()
            logger.error(f"MCP execute_profiler_tool failed: {exc}; trace={trace}")
            raise RuntimeError(f"MCP_TOOL_ERROR: {exc}; trace={trace}") from exc

        elapsed_ms = int((time.time() - start) * 1000)
        text = self._extract_text(raw)
        safe_raw = self._safe_raw(raw)
        structured = self._structured_payload(safe_raw)
        control_flow = self.parser.parse_control_flow(structured)
        data = self.parser.parse_data(structured)
        next_step = self.parser.parse_next_step_from_data(structured)
        if not next_step and control_flow.status == "SUCCESS":
            next_step = self.parser.parse_next_step(text)
        requires_input = control_flow.status == "NEEDS_USER_INPUT"
        status = "completed" if control_flow.status in {"SUCCESS", "BLOCKED", "NEEDS_USER_INPUT"} else "failed"
        error = None
        if control_flow.status in {"RETRYABLE_ERROR", "FATAL_ERROR"}:
            error = data.get("error") or control_flow.developer_message or control_flow.user_message or text
        return MCPToolResult(
            status=status,
            tool_name=tool_name,
            text=text,
            next_step=next_step,
            requires_user_input=requires_input,
            error=error,
            elapsed_ms=elapsed_ms,
            raw=safe_raw,
            control_flow=control_flow,
            data=data,
        )

    async def health(self) -> Dict[str, Any]:
        try:
            connected = await self.client.connect()
            if connected:
                await self.ensure_tools_loaded(force=True)
            return {
                "status": "healthy" if connected and not self.missing_required_tools else "unavailable",
                "transport": self.config.transport,
                "tools": list(self.tools_by_name.keys()),
                "tool_count": len(self.tools_by_name),
                "required_meta_tools": self.config.required_meta_tools,
                "missing_required_tools": self.missing_required_tools,
                "tools_list_trace": self.last_tools_list_trace,
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "transport": self.config.transport,
                "error": str(exc),
                "tools": list(self.tools_by_name.keys()),
                "tool_count": len(self.tools_by_name),
                "required_meta_tools": self.config.required_meta_tools,
                "missing_required_tools": self.missing_required_tools,
                "tools_list_trace": self.last_tools_list_trace or self._last_trace(),
            }

    async def close(self) -> None:
        await self.client.disconnect()

    def _extract_text(self, raw: Any) -> str:
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            if "parsedContent" in raw:
                parsed = raw["parsedContent"]
                if isinstance(parsed, str):
                    return parsed
                return str(parsed)
            if "content" in raw and isinstance(raw["content"], list):
                return "\n".join(str(item.get("text", item)) for item in raw["content"])
            if "text" in raw:
                return str(raw["text"])
            if "result" in raw:
                return self._extract_text(raw["result"])
            return str(raw)
        if isinstance(raw, list):
            parts = []
            for item in raw:
                if isinstance(item, dict):
                    parts.append(str(item.get("text", item)))
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return str(raw)

    def _safe_raw(self, raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        return {"value": raw}

    def _structured_payload(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        parsed = raw.get("parsedContent")
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, str):
            parsed_json = self._json_object(parsed)
            if parsed_json:
                return parsed_json
        structured = raw.get("structuredContent") or raw.get("structured_content")
        if isinstance(structured, dict):
            return structured
        if isinstance(structured, str):
            structured_json = self._json_object(structured)
            if structured_json:
                return structured_json
        if "content" in raw and isinstance(raw["content"], list):
            for item in raw["content"]:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        content_json = self._json_object(text)
                        if content_json:
                            return content_json
        text = raw.get("text")
        if isinstance(text, str):
            text_json = self._json_object(text)
            if text_json:
                return text_json
        result = raw.get("result")
        if isinstance(result, dict):
            return self._structured_payload(result)
        if isinstance(result, str):
            result_json = self._json_object(result)
            if result_json:
                return result_json
        return raw

    def _json_object(self, text: str) -> Optional[Dict[str, Any]]:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _last_trace(self) -> Optional[Dict[str, Any]]:
        transport = getattr(self.client, "_transport", None)
        trace = getattr(transport, "last_trace", None)
        return trace if isinstance(trace, dict) else None
