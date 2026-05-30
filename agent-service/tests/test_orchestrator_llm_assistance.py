"""测试 Orchestrator 中的受控 LLM 辅助集成"""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.mcp_llm_assistant import MCPLLMOrchestrationAssistant
from src.core.orchestrator import Orchestrator
from src.models.config import LLMAssistanceConfig
from src.models.orchestration import MCPNextStep, MCPSearchResult, MCPToolResult
from src.storage.session_store import SessionStore


class FakeRAGClient:
    async def retrieve(self, query):
        raise AssertionError("RAG should not be called")


class FakeMCPGateway:
    def __init__(self, search_result):
        self.search_result = search_result
        self.search_calls = []
        self.executed = []

    async def ensure_tools_loaded(self):
        return [{"name": "search_profiler_tools", "description": "可选剧本：straggler 关键词：快慢卡"}]

    async def search_profiler_tools(self, query, select_playbook=None):
        self.search_calls.append((query, select_playbook))
        return self.search_result

    async def execute_profiler_tool(self, tool_name, arguments):
        self.executed.append((tool_name, arguments))
        return MCPToolResult(status="completed", tool_name=tool_name, text="剧本执行完成")

    def _last_trace(self):
        return {"transport": "test"}

    async def close(self):
        pass


class FakeLLMRouter:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, messages, tools=None, provider=None, **kwargs):
        self.calls.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return {"content": response}


def make_orchestrator(gateway, llm_router, tmp_path):
    assistant = MCPLLMOrchestrationAssistant(llm_router, LLMAssistanceConfig(enabled=True, timeout_seconds=0.2))
    return Orchestrator(
        session_store=SessionStore(str(tmp_path / "sessions.db")),
        rag_client=FakeRAGClient(),
        mcp_gateway=gateway,
        config=SimpleNamespace(
            auto_execute=True,
            max_auto_steps=5,
            require_confirmation_for_side_effects=True,
            side_effect_tool_patterns=["delete_*", "write_*"],
        ),
        llm_router=llm_router,
        llm_assistant=assistant,
    )


@pytest.mark.asyncio
async def test_search_uses_rewritten_query(tmp_path):
    search = MCPSearchResult(
        status="completed",
        text="ok",
        initial_step=MCPNextStep(tool_name="pt_snap_list_templates", schema={"properties": {}}),
    )
    gateway = FakeMCPGateway(search)
    llm = FakeLLMRouter(['{}', '{"rewritten_query":"memory snapshot search"}'])
    orchestrator = make_orchestrator(gateway, llm, tmp_path)

    await _drain(orchestrator._handle_diagnosis("ses_llm_1", "显存一直涨", {}, None))

    assert gateway.search_calls[0] == ("memory snapshot search", None)


@pytest.mark.asyncio
async def test_candidate_recommendation_reorders_low_confidence_pending_options_only(tmp_path):
    search = MCPSearchResult(
        status="completed",
        text="请选择",
        playbook_candidates=[{"id": "comm", "description": "通信"}, {"id": "memory", "description": "显存"}],
        requires_user_choice=True,
    )
    gateway = FakeMCPGateway(search)
    llm = FakeLLMRouter([
        '{}',
        '{}',
        '{"recommendations":[{"playbook_id":"memory","confidence":0.6,"reason":"显存匹配"},{"playbook_id":"invented","confidence":1.0}]}',
    ])
    orchestrator = make_orchestrator(gateway, llm, tmp_path)

    events = await _drain(orchestrator._handle_diagnosis("ses_llm_2", "显存问题", {}, None))

    pending = next(event for event in events if event.event == "user_input_required")
    assert [option["value"] for option in pending.data["options"]] == ["memory", "comm"]
    assert gateway.executed == []


@pytest.mark.asyncio
async def test_high_confidence_candidate_recommendation_selects_playbook(tmp_path):
    ambiguous_search = MCPSearchResult(
        status="completed",
        text="请选择",
        playbook_candidates=[{"id": "comm", "description": "通信"}, {"id": "straggler", "description": "快慢卡"}],
        requires_user_choice=True,
    )
    selected_search = MCPSearchResult(
        status="completed",
        text="ok",
        selected_playbook="straggler",
        initial_step=MCPNextStep(tool_name="pt_straggler_detect", schema={"properties": {}}),
    )
    gateway = FakeMCPGateway(ambiguous_search)
    llm = FakeLLMRouter([
        '{}',
        '{}',
        '{"recommendations":[{"playbook_id":"straggler","confidence":0.92,"reason":"用户明确要求快慢卡分析"}]}',
        '{}',
    ])

    async def search_profiler_tools(query, select_playbook=None):
        gateway.search_calls.append((query, select_playbook))
        return selected_search if select_playbook == "straggler" else ambiguous_search

    gateway.search_profiler_tools = search_profiler_tools
    orchestrator = make_orchestrator(gateway, llm, tmp_path)

    events = await _drain(orchestrator._handle_diagnosis("ses_llm_select", "分析快慢卡问题", {}, None))

    assert gateway.search_calls == [("分析快慢卡问题", None), ("分析快慢卡问题", "straggler")]
    assert gateway.executed[0] == ("pt_straggler_detect", {})
    assert not any(event.event == "user_input_required" for event in events)


@pytest.mark.asyncio
async def test_parameter_extraction_fills_schema_field_without_overriding(tmp_path):
    search = MCPSearchResult(
        status="completed",
        text="ok",
        initial_step=MCPNextStep(tool_name="pt_snap_focus_rank", schema={"properties": {"query": {"type": "string"}, "rank": {"type": "integer"}}, "required": ["query", "rank"]}),
    )
    gateway = FakeMCPGateway(search)
    llm = FakeLLMRouter([
        '{}',
        '{}',
        '{"parameters":{"query":"override","rank":3,"unknown":"x"},"missing_required":[],"confidence":0.8}',
        '{"parameters":{"query":"override","rank":3,"unknown":"x"},"missing_required":[],"confidence":0.8}',
    ])
    orchestrator = make_orchestrator(gateway, llm, tmp_path)

    await _drain(orchestrator._handle_diagnosis("ses_llm_3", "看 rank 3 的显存", {}, None))

    assert gateway.executed[0] == ("pt_snap_focus_rank", {"query": "看 rank 3 的显存", "rank": 3})


@pytest.mark.asyncio
async def test_llm_failure_does_not_fail_orchestration(tmp_path):
    search = MCPSearchResult(
        status="completed",
        text="ok",
        initial_step=MCPNextStep(tool_name="pt_snap_list_templates", schema={"properties": {}}),
    )
    gateway = FakeMCPGateway(search)
    llm = FakeLLMRouter([RuntimeError("llm down"), RuntimeError("llm down")])
    orchestrator = make_orchestrator(gateway, llm, tmp_path)

    events = await _drain(orchestrator._handle_diagnosis("ses_llm_4", "显存问题", {}, None))

    assert gateway.search_calls[0] == ("显存问题", None)
    assert gateway.executed[0] == ("pt_snap_list_templates", {})
    assert any(event.event == "analysis_result" for event in events)


async def _drain(generator):
    return [event async for event in generator]
