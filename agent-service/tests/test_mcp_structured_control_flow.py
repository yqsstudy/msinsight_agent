"""Tests for structured MCP control_flow parsing."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.adapters.mcp_response_parser import MCPResponseParser


def test_parse_success_control_flow_and_next_step():
    parser = MCPResponseParser()
    raw = {
        "control_flow": {"status": "SUCCESS"},
        "data": {"summary": "done"},
        "next_step": {
            "tool_name": "next_tool",
            "action": "continue",
            "schema": {"properties": {"query": {"type": "string"}}},
            "progress": {"completed": 1, "total": 2},
        },
    }

    control_flow = parser.parse_control_flow(raw)
    next_step = parser.parse_next_step_from_data(raw)

    assert control_flow.status == "SUCCESS"
    assert parser.parse_data(raw) == {"summary": "done"}
    assert next_step.tool_name == "next_tool"
    assert next_step.schema_["properties"]["query"]["type"] == "string"


def test_missing_control_flow_is_protocol_error():
    parser = MCPResponseParser()

    control_flow = parser.parse_control_flow({"data": {}})

    assert control_flow.status == "FATAL_ERROR"
    assert control_flow.reason == "MCP_PROTOCOL_ERROR"
    assert control_flow.retryable is False


def test_blocked_waiting_for_event_requires_event_name():
    parser = MCPResponseParser()

    control_flow = parser.parse_control_flow({
        "control_flow": {
            "status": "BLOCKED",
            "reason": "WAITING_FOR_EVENT",
            "retryable": True,
        },
        "data": {},
    })

    assert control_flow.status == "FATAL_ERROR"
    assert control_flow.reason == "MCP_PROTOCOL_ERROR"


def test_parse_needs_user_input_required_inputs():
    parser = MCPResponseParser()

    control_flow = parser.parse_control_flow({
        "control_flow": {
            "status": "NEEDS_USER_INPUT",
            "reason": "MISSING_REQUIRED_PARAMETER",
            "retryable": False,
            "required_inputs": [
                {"name": "profile_path", "type": "string", "description": "请提供 profiling 数据路径"}
            ],
        },
        "data": {},
    })

    assert control_flow.status == "NEEDS_USER_INPUT"
    assert control_flow.required_inputs[0].name == "profile_path"


def test_unknown_status_is_protocol_error():
    parser = MCPResponseParser()

    control_flow = parser.parse_control_flow({
        "control_flow": {"status": "OLD_ERROR"},
        "data": {},
    })

    assert control_flow.status == "FATAL_ERROR"
    assert control_flow.reason == "MCP_PROTOCOL_ERROR"
