"""测试受控 MCP LLM 辅助器"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.mcp_llm_assistant import MCPLLMOrchestrationAssistant
from src.models.config import LLMAssistanceConfig
from src.models.orchestration import MCPNextStep


class FakeLLMRouter:
    def __init__(self, content=None, exc=None):
        self.chat = AsyncMock()
        if exc:
            self.chat.side_effect = exc
        else:
            self.chat.return_value = {"content": content or "{}"}


def enabled_config(**overrides):
    values = {"enabled": True, "timeout_seconds": 0.2}
    values.update(overrides)
    return LLMAssistanceConfig(**values)


@pytest.mark.asyncio
async def test_disabled_assistant_does_not_call_llm():
    llm = FakeLLMRouter('{"rewritten_query":"x"}')
    assistant = MCPLLMOrchestrationAssistant(llm, LLMAssistanceConfig(enabled=False))
    step = MCPNextStep(tool_name="tool", schema={"properties": {"rank": {"type": "integer"}}})

    assert await assistant.rewrite_query("原始问题") == "原始问题"
    assert await assistant.recommend_playbook_candidate("问题", [{"id": "a"}]) == [{"id": "a"}]
    assert await assistant.extract_parameters("rank 3", step, {"file_path": "/tmp/a"}) == {"file_path": "/tmp/a"}
    assert await assistant.enhance_summary("确定性总结", {"a": 1}) == "确定性总结"
    llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_query_rewrite_success():
    llm = FakeLLMRouter('{"rewritten_query":"PyTorch memory leak snapshot","rationale":"matches symptom"}')
    assistant = MCPLLMOrchestrationAssistant(llm, enabled_config())

    rewritten = await assistant.rewrite_query("显存一直涨最后 OOM")

    assert rewritten == "PyTorch memory leak snapshot"
    llm.chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_query_rewrite_invalid_json_falls_back():
    assistant = MCPLLMOrchestrationAssistant(FakeLLMRouter("not json"), enabled_config())

    assert await assistant.rewrite_query("原始问题") == "原始问题"


@pytest.mark.asyncio
async def test_playbook_selection_from_tools_uses_declared_playbook_only():
    llm = FakeLLMRouter('{"select_playbook":"pt_straggler_analysis","query":"slow rank straggler","confidence":0.91,"reason":"用户要求快慢卡"}')
    assistant = MCPLLMOrchestrationAssistant(llm, enabled_config())
    tools = [{"name": "search_profiler_tools", "description": "可选剧本：pt_straggler_analysis 关键词：快慢卡 straggler"}]

    selection = await assistant.select_playbook_from_tools("是否有快慢卡问题", tools)

    assert selection["select_playbook"] == "pt_straggler_analysis"
    assert selection["query"] == "slow rank straggler"


@pytest.mark.asyncio
async def test_playbook_selection_rejects_undeclared_playbook():
    llm = FakeLLMRouter('{"select_playbook":"invented","query":"x","confidence":0.99}')
    assistant = MCPLLMOrchestrationAssistant(llm, enabled_config())
    tools = [{"name": "search_profiler_tools", "description": "可选剧本：pt_straggler_analysis"}]

    assert await assistant.select_playbook_from_tools("快慢卡", tools) == {}


@pytest.mark.asyncio
async def test_candidate_recommendation_allowlists_candidates():
    llm = FakeLLMRouter('{"recommendations":[{"playbook_id":"memory","confidence":0.9,"reason":"显存问题"},{"playbook_id":"invented","confidence":1.0}]}')
    assistant = MCPLLMOrchestrationAssistant(llm, enabled_config())
    candidates = [{"id": "comm", "description": "通信"}, {"id": "memory", "description": "显存"}]

    ranked = await assistant.recommend_playbook_candidate("显存问题", candidates)

    assert [item["id"] for item in ranked] == ["memory", "comm"]
    assert ranked[0]["llm_recommendation_reason"] == "显存问题"


@pytest.mark.asyncio
async def test_parameter_extraction_filters_unknown_and_preserves_existing():
    llm = FakeLLMRouter('{"parameters":{"data_id":"other","rank":3,"unknown":"x"},"missing_required":[],"confidence":0.8}')
    assistant = MCPLLMOrchestrationAssistant(llm, enabled_config())
    step = MCPNextStep(tool_name="tool", schema={"properties": {"data_id": {"type": "string"}, "rank": {"type": "integer"}}})

    params = await assistant.extract_parameters("看 rank 3", step, {"data_id": "abc"})

    assert params == {"data_id": "abc", "rank": 3}


@pytest.mark.asyncio
async def test_llm_failure_falls_back():
    assistant = MCPLLMOrchestrationAssistant(FakeLLMRouter(exc=RuntimeError("boom")), enabled_config())
    step = MCPNextStep(tool_name="tool", schema={"properties": {"rank": {"type": "integer"}}})

    assert await assistant.rewrite_query("原始") == "原始"
    assert await assistant.extract_parameters("rank 3", step, {}) == {}


@pytest.mark.asyncio
async def test_summary_enhancement_disabled_by_default():
    llm = FakeLLMRouter('{"summary":"润色总结"}')
    assistant = MCPLLMOrchestrationAssistant(llm, enabled_config(summary_enhancement_enabled=False))

    assert await assistant.enhance_summary("确定性总结", {"evidence": "x"}) == "确定性总结"
    llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_summary_enhancement_rejects_empty_summary():
    assistant = MCPLLMOrchestrationAssistant(FakeLLMRouter('{"summary":""}'), enabled_config(summary_enhancement_enabled=True))

    assert await assistant.enhance_summary("确定性总结", {"evidence": "x"}) == "确定性总结"
