"""Parsers for current text-heavy MCP meta-tool responses."""

import json
import re
from typing import Any, Dict, Optional

from ..models.orchestration import ControlFlow, MCPNextStep, RequiredInput


NEXT_TOOL_PATTERNS = [
    re.compile(r"\*\*工具\*\*:\s*`([^`]+)`"),
    re.compile(r"工具\s*[:：]\s*`?([a-zA-Z0-9_\-]+)`?"),
]

PLAYBOOK_PATTERN = re.compile(r"已自动选择剧本\s*[:：]\s*([a-zA-Z0-9_\-]+)")
PROGRESS_PATTERN = re.compile(r"进度\s*[:：]\s*(\d+)\s*/\s*(\d+)\s*\((\d+)%\)")
SCHEMA_PATTERN = re.compile(r"参数 Schema.*?\n```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


class MCPResponseParser:
    """Extracts lightweight structure from MCP text responses."""

    VALID_STATUSES = {"SUCCESS", "BLOCKED", "RETRYABLE_ERROR", "FATAL_ERROR", "NEEDS_USER_INPUT"}
    VALID_REASONS = {
        "WAITING_FOR_EVENT",
        "RESOURCE_UNAVAILABLE",
        "RATE_LIMITED",
        "MISSING_REQUIRED_PARAMETER",
        "USER_CONFIRMATION_REQUIRED",
        "INVALID_PARAMETER",
        "BACKEND_ERROR",
        "TIMEOUT",
        "MCP_PROTOCOL_ERROR",
    }

    def parse_control_flow(self, data: Dict[str, Any]) -> ControlFlow:
        control_flow = data.get("control_flow") or data.get("controlFlow")
        if not isinstance(control_flow, dict):
            return self.protocol_error("Missing or invalid control_flow")

        status = control_flow.get("status")
        if not isinstance(status, str) or status not in self.VALID_STATUSES:
            return self.protocol_error(f"Invalid control_flow.status: {status}")

        reason = control_flow.get("reason")
        if reason is not None and reason not in self.VALID_REASONS:
            return self.protocol_error(f"Invalid control_flow.reason: {reason}")

        required_inputs_raw = control_flow.get("required_inputs") or control_flow.get("requiredInputs") or []
        required_inputs: list[RequiredInput] = []
        if isinstance(required_inputs_raw, list):
            for item in required_inputs_raw:
                if isinstance(item, dict) and item.get("name"):
                    required_inputs.append(RequiredInput(**item))
        elif status == "NEEDS_USER_INPUT":
            return self.protocol_error("NEEDS_USER_INPUT requires required_inputs")

        if status != "SUCCESS" and not reason:
            return self.protocol_error(f"{status} requires reason")
        if status in {"BLOCKED", "RETRYABLE_ERROR"} and not isinstance(control_flow.get("retryable"), bool):
            return self.protocol_error(f"{status} requires retryable")
        if reason == "WAITING_FOR_EVENT" and not control_flow.get("event_name"):
            return self.protocol_error("WAITING_FOR_EVENT requires event_name")
        if status == "NEEDS_USER_INPUT" and not required_inputs:
            return self.protocol_error("NEEDS_USER_INPUT requires required_inputs")

        return ControlFlow(
            status=status,
            reason=reason,
            retryable=control_flow.get("retryable"),
            suggested_retry_after_ms=control_flow.get("suggested_retry_after_ms") or control_flow.get("suggestedRetryAfterMs"),
            event_name=control_flow.get("event_name") or control_flow.get("eventName"),
            operation_id=control_flow.get("operation_id") or control_flow.get("operationId"),
            required_inputs=required_inputs,
            message_params=control_flow.get("message_params") or control_flow.get("messageParams") or {},
            user_message=control_flow.get("user_message") or control_flow.get("userMessage"),
            developer_message=control_flow.get("developer_message") or control_flow.get("developerMessage"),
        )

    def protocol_error(self, message: str) -> ControlFlow:
        return ControlFlow(
            status="FATAL_ERROR",
            reason="MCP_PROTOCOL_ERROR",
            retryable=False,
            developer_message=message,
        )

    def parse_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        payload = data.get("data")
        return payload if isinstance(payload, dict) else {}

    def parse_next_step_from_data(self, data: Dict[str, Any]) -> Optional[MCPNextStep]:
        step = self._find_first_dict(data, ["next_step", "nextStep"])
        if step:
            parsed = self._step_from_dict(step)
            if parsed and parsed.tool_name:
                return parsed
        return None

    def parse_auto_selected_playbook(self, text: str) -> Optional[str]:
        match = PLAYBOOK_PATTERN.search(text or "")
        return match.group(1) if match else None

    def parse_initial_step(self, data: Dict[str, Any], text: str) -> Optional[MCPNextStep]:
        step = self._find_first_dict(data, ["initial_step", "initialStep", "first_step", "firstStep", "next_step", "nextStep"])
        if step:
            parsed = self._step_from_dict(step)
            if parsed and parsed.tool_name:
                return parsed
        return self.parse_next_step(text)

    def parse_candidates(self, data: Dict[str, Any], text: Optional[str] = None) -> list[Dict[str, Any]]:
        candidates = self._find_first_list(data, ["playbook_candidates", "candidates", "playbooks"])
        if candidates:
            return [item for item in candidates if isinstance(item, dict)]
            
        # Fallback to regex parsing from text
        if text:
            # Match patterns like:
            # 1. **pt_snap_memory_analysis**
            #    PyTorch 内存快照分析剧本 [Step 1-4]
            results = []
            pattern = re.compile(r"\d+\.\s*\*\*([a-zA-Z0-9_\-]+)\*\*(?:\s*⭐)?\n\s*([^\[\n]+)", re.MULTILINE)
            for match in pattern.finditer(text):
                playbook_id = match.group(1).strip()
                description = match.group(2).strip()
                results.append({
                    "id": playbook_id,
                    "name": playbook_id,
                    "description": description
                })
            return results
        return []

    def parse_suggested_arguments(self, data: Dict[str, Any]) -> Dict[str, Any]:
        arguments = self._find_first_dict(data, ["arguments", "args", "suggested_arguments", "suggestedArguments", "default_arguments", "defaultArguments"])
        return arguments or {}

    def parse_selected_playbook(self, data: Dict[str, Any], text: str) -> Optional[str]:
        for key in ("selected_playbook", "selectedPlaybook", "playbook_id", "playbookId", "id"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        playbook = data.get("playbook")
        if isinstance(playbook, dict):
            for key in ("id", "playbook_id", "playbookId", "name"):
                value = playbook.get(key)
                if isinstance(value, str) and value:
                    return value
        return self.parse_auto_selected_playbook(text)

    def parse_next_step(self, text: str) -> Optional[MCPNextStep]:
        if not text:
            return None
        if "剧本执行完成" in text:
            return None

        tool_name = None
        for pattern in NEXT_TOOL_PATTERNS:
            match = pattern.search(text)
            if match:
                tool_name = match.group(1)
                break
        if not tool_name:
            return None

        schema: Dict[str, Any] = {}
        schema_match = SCHEMA_PATTERN.search(text)
        if schema_match:
            try:
                schema = json.loads(schema_match.group(1))
            except json.JSONDecodeError:
                schema = {}

        progress: Dict[str, Any] = {}
        progress_match = PROGRESS_PATTERN.search(text)
        if progress_match:
            completed, total, percentage = progress_match.groups()
            progress = {
                "completed": int(completed),
                "total": int(total),
                "percentage": int(percentage),
            }

        action = None
        action_match = re.search(r"下一步\s*[:：][^\n]*-\s*([^\n]+)", text)
        if action_match:
            action = action_match.group(1).strip()

        return MCPNextStep(tool_name=tool_name, action=action, schema=schema, progress=progress)

    def requires_user_input(self, text: str) -> bool:
        markers = [
            "请选择",
            "需要用户",
            "向用户要",
            "缺少",
            "参数校验",
            "必须",
            "⛔",
        ]
        return any(marker in (text or "") for marker in markers)

    def is_completed(self, text: str) -> bool:
        return "剧本执行完成" in (text or "") or "分析结束" in (text or "")

    def _step_from_dict(self, data: Dict[str, Any]) -> Optional[MCPNextStep]:
        tool_name = data.get("tool_name") or data.get("toolName") or data.get("tool") or data.get("name")
        if not isinstance(tool_name, str) or not tool_name:
            return None
        schema = data.get("schema") or data.get("input_schema") or data.get("inputSchema") or {}
        progress = data.get("progress") or {}
        action = data.get("action") or data.get("description")
        return MCPNextStep(
            tool_name=tool_name,
            action=str(action) if action is not None else None,
            schema=schema if isinstance(schema, dict) else {},
            progress=progress if isinstance(progress, dict) else {},
        )

    def _find_first_dict(self, data: Dict[str, Any], keys: list[str]) -> Optional[Dict[str, Any]]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, dict):
                return value
        for value in data.values():
            if isinstance(value, dict):
                found = self._find_first_dict(value, keys)
                if found:
                    return found
        return None

    def _find_first_list(self, data: Dict[str, Any], keys: list[str]) -> list[Any]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
        for value in data.values():
            if isinstance(value, dict):
                found = self._find_first_list(value, keys)
                if found:
                    return found
        return []
