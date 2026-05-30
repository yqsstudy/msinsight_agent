"""Parsers for current text-heavy MCP meta-tool responses."""

import json
import re
from typing import Any, Dict, Optional

from ..models.orchestration import MCPNextStep


NEXT_TOOL_PATTERNS = [
    re.compile(r"\*\*工具\*\*:\s*`([^`]+)`"),
    re.compile(r"工具\s*[:：]\s*`?([a-zA-Z0-9_\-]+)`?"),
]

PLAYBOOK_PATTERN = re.compile(r"已自动选择剧本\s*[:：]\s*([a-zA-Z0-9_\-]+)")
PROGRESS_PATTERN = re.compile(r"进度\s*[:：]\s*(\d+)\s*/\s*(\d+)\s*\((\d+)%\)")
SCHEMA_PATTERN = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


class MCPResponseParser:
    """Extracts lightweight structure from MCP text responses."""

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

    def parse_candidates(self, data: Dict[str, Any]) -> list[Dict[str, Any]]:
        candidates = self._find_first_list(data, ["playbook_candidates", "candidates", "playbooks"])
        return [item for item in candidates if isinstance(item, dict)]

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
