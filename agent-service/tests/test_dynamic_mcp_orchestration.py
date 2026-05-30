"""测试动态 MCP playbook 编排"""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.orchestrator import Orchestrator
from src.models.orchestration import MCPNextStep, MCPSearchResult, MCPToolResult
from src.storage.session_store import SessionStore


class FakeRAGClient:
    async def retrieve(self, query):
        raise AssertionError("RAG should not be called in these tests")


class FakeMCPGateway:
    def __init__(self, search_result, tool_results=None):
        self.search_result = search_result
        self.tool_results = list(tool_results or [])
        self.executed = []

    async def ensure_tools_loaded(self):
        return [{"name": "search_profiler_tools", "description": "可选剧本：pt_snap_memory_analysis comm_slow_rank custom"}]

    async def search_profiler_tools(self, query, select_playbook=None):
        self.search_query = query
        self.select_playbook = select_playbook
        return self.search_result

    async def execute_profiler_tool(self, tool_name, arguments):
        self.executed.append((tool_name, arguments))
        if self.tool_results:
            return self.tool_results.pop(0)
        return MCPToolResult(status="completed", tool_name=tool_name, text="剧本执行完成")

    def _last_trace(self):
        return {"transport": "test"}

    async def close(self):
        pass


def make_orchestrator(mcp_gateway, tmp_path):
    return Orchestrator(
        session_store=SessionStore(str(tmp_path / "sessions.db")),
        rag_client=FakeRAGClient(),
        mcp_gateway=mcp_gateway,
        config=SimpleNamespace(
            auto_execute=True,
            max_auto_steps=5,
            require_confirmation_for_side_effects=True,
            side_effect_tool_patterns=["delete_*", "write_*"],
        ),
    )


@pytest.mark.asyncio
async def test_dynamic_initial_step_is_executed_without_import_trace_file(tmp_path):
    search = MCPSearchResult(
        status="completed",
        text="已自动选择剧本：pt_snap_memory_analysis",
        selected_playbook="pt_snap_memory_analysis",
        initial_step=MCPNextStep(tool_name="pt_snap_set_focus", schema={"properties": {"query": {"type": "string"}}, "required": ["query"]}),
    )
    gateway = FakeMCPGateway(search)
    orchestrator = make_orchestrator(gateway, tmp_path)

    events = [event async for event in orchestrator._handle_diagnosis("ses_1", "PyTorch 显存泄漏 memory snapshot", {}, None)]

    assert gateway.executed[0] == ("pt_snap_set_focus", {"query": "PyTorch 显存泄漏 memory snapshot"})
    assert all(call[0] != "import_trace_file" for call in gateway.executed)
    assert any(event.event == "mcp_tool_result" for event in events)


@pytest.mark.asyncio
async def test_initial_step_without_path_does_not_require_path(tmp_path):
    search = MCPSearchResult(
        status="completed",
        text="已自动选择剧本：pt_snap_memory_analysis",
        selected_playbook="pt_snap_memory_analysis",
        initial_step=MCPNextStep(tool_name="pt_snap_list_templates", schema={"properties": {}}),
    )
    gateway = FakeMCPGateway(search)
    orchestrator = make_orchestrator(gateway, tmp_path)

    events = [event async for event in orchestrator._handle_diagnosis("ses_2", "列出 memory snapshot 模板", {}, None)]

    assert gateway.executed[0] == ("pt_snap_list_templates", {})
    assert not any(event.event == "user_input_required" and event.data.get("input_type") == "path" for event in events)


@pytest.mark.asyncio
async def test_multiple_playbook_candidates_require_user_choice(tmp_path):
    search = MCPSearchResult(
        status="completed",
        text="请选择剧本",
        playbook_candidates=[
            {"id": "pt_snap_memory_analysis", "description": "显存分析"},
            {"id": "comm_slow_rank", "description": "慢卡分析"},
        ],
        requires_user_choice=True,
    )
    gateway = FakeMCPGateway(search)
    orchestrator = make_orchestrator(gateway, tmp_path)

    events = [event async for event in orchestrator._handle_diagnosis("ses_3", "分析一下", {}, None)]

    pending = next(event for event in events if event.event == "user_input_required")
    assert pending.data["input_type"] == "choice"
    assert pending.data["metadata"]["resume_action"] == "select_playbook"
    assert gateway.executed == []


@pytest.mark.asyncio
async def test_missing_initial_step_required_args_requires_params(tmp_path):
    search = MCPSearchResult(
        status="completed",
        text="已自动选择剧本：custom",
        selected_playbook="custom",
        initial_step=MCPNextStep(tool_name="pt_snap_set_focus", schema={"properties": {"snapshot_id": {"type": "string"}}, "required": ["snapshot_id"]}),
    )
    gateway = FakeMCPGateway(search)
    orchestrator = make_orchestrator(gateway, tmp_path)

    events = [event async for event in orchestrator._handle_diagnosis("ses_4", "分析显存", {}, None)]

    pending = next(event for event in events if event.event == "user_input_required")
    assert pending.data["input_type"] == "params"
    assert pending.data["metadata"]["resume_action"] == "continue_mcp_with_args"
    assert pending.data["metadata"]["tool_name"] == "pt_snap_set_focus"
    assert gateway.executed == []


@pytest.mark.asyncio
async def test_next_step_tool_name_comes_from_mcp_result(tmp_path):
    search = MCPSearchResult(
        status="completed",
        text="已自动选择剧本：pt_snap_memory_analysis",
        selected_playbook="pt_snap_memory_analysis",
        initial_step=MCPNextStep(tool_name="pt_snap_set_focus", schema={"properties": {}}),
    )
    first_result = MCPToolResult(
        status="completed",
        tool_name="pt_snap_set_focus",
        text="下一步：\n**工具**: `pt_snap_list_templates`",
        next_step=MCPNextStep(tool_name="pt_snap_list_templates", schema={"properties": {}}),
    )
    gateway = FakeMCPGateway(search, [first_result, MCPToolResult(status="completed", tool_name="pt_snap_list_templates", text="剧本执行完成")])
    orchestrator = make_orchestrator(gateway, tmp_path)

    events = [event async for event in orchestrator._handle_diagnosis("ses_5", "分析显存", {}, None)]

    assert gateway.executed == [("pt_snap_set_focus", {}), ("pt_snap_list_templates", {})]
    assert any(event.event == "analysis_result" for event in events)
