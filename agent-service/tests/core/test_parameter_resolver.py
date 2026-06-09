import os
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.core.diagnosis import DiagnosisContextManager, ParameterResolver
from src.core.diagnosis.models import ConflictSeverity, ParamSource
from src.models.orchestration import MCPNextStep


class FakeLLMAssistant:
    def __init__(self, result):
        self.extract_parameters_by_schema = AsyncMock(return_value=result)


def step(schema):
    return MCPNextStep(tool_name="tool", schema=schema)


@pytest.mark.asyncio
async def test_resolver_reuses_initial_path_alias_without_user_prompt():
    context = DiagnosisContextManager.create("ses_1", "分析 /tmp/trace", extracted={"path": "/tmp/trace"})
    resolver = ParameterResolver()
    result = await resolver.resolve_for_step(
        context,
        step({"properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}),
    )

    assert result.arguments == {"file_path": "/tmp/trace"}
    assert result.missing_required == []
    assert result.question_reason is None


@pytest.mark.asyncio
async def test_resolver_reuses_mcp_output_params_and_records_sources():
    context = DiagnosisContextManager.create("ses_1", "goal")
    DiagnosisContextManager.apply_step_result(
        context,
        tool_name="find_slow_rank",
        arguments={},
        result_summary={"produced_params": {"rank": 3}},
        produced_params={"rank": 3},
    )
    resolver = ParameterResolver()

    result = await resolver.resolve_for_step(
        context,
        step({"properties": {"rank": {"type": "integer"}}, "required": ["rank"]}),
    )

    assert result.arguments == {"rank": 3}
    assert result.filled[0].source == ParamSource.MCP_OUTPUT
    assert result.missing_required == []


@pytest.mark.asyncio
async def test_user_explicit_input_overrides_suggested_arg_and_reports_conflict():
    context = DiagnosisContextManager.create("ses_1", "goal")
    resolver = ParameterResolver()

    result = await resolver.resolve_for_step(
        context,
        step({"properties": {"rank": {"type": "integer"}}, "required": ["rank"]}),
        suggested_args={"rank": 1},
        current_user_input={"rank": 2},
    )

    assert result.arguments["rank"] == 2
    assert len(result.conflicts) == 1
    assert result.conflicts[0].severity == ConflictSeverity.WARNING


@pytest.mark.asyncio
async def test_user_conflict_with_executed_provenance_requires_invalidation():
    context = DiagnosisContextManager.create("ses_1", "goal")
    DiagnosisContextManager.apply_step_result(
        context,
        tool_name="find_slow_rank",
        arguments={},
        result_summary={},
        produced_params={"rank": 3},
    )
    resolver = ParameterResolver()

    result = await resolver.resolve_for_step(
        context,
        step({"properties": {"rank": {"type": "integer"}}, "required": ["rank"]}),
        current_user_input={"rank": 4},
    )

    assert result.arguments["rank"] == 4
    assert result.needs_confirmation is True
    assert result.conflicts[0].severity == ConflictSeverity.REQUIRES_INVALIDATION
    assert result.conflicts[0].affected_step_index == 1


@pytest.mark.asyncio
async def test_llm_conflict_does_not_override_high_confidence_param():
    context = DiagnosisContextManager.create("ses_1", "goal")
    DiagnosisContextManager.add_or_update_param(context, "rank", 3, ParamSource.USER_INITIAL)
    llm = FakeLLMAssistant({"rank": 4, "unknown": "x"})
    resolver = ParameterResolver(llm)

    result = await resolver.resolve_for_step(
        context,
        step({"properties": {"rank": {"type": "integer"}}, "required": ["rank"]}),
        current_user_input="帮我看一下",
    )

    assert result.arguments == {"rank": 3}
    assert result.conflicts[0].new_source == ParamSource.LLM_EXTRACTION
    llm.extract_parameters_by_schema.assert_awaited_once()
    call_kwargs = llm.extract_parameters_by_schema.await_args.kwargs
    assert "context" in call_kwargs
    assert call_kwargs["context"]["diagnosis_id"] == context.diagnosis_id


@pytest.mark.asyncio
async def test_resolver_schema_filters_unknown_fields_and_reports_missing():
    context = DiagnosisContextManager.create("ses_1", "goal")
    resolver = ParameterResolver()

    result = await resolver.resolve_for_step(
        context,
        step({"properties": {"rank": {"type": "integer"}}, "required": ["rank", "iteration"]}),
        suggested_args={"rank": 1, "unknown": "x"},
    )

    assert result.arguments == {"rank": 1}
    assert result.missing_required == ["iteration"]
    assert result.question_reason == "missing_required_arguments"


@pytest.mark.asyncio
async def test_single_value_maps_to_single_schema_property():
    context = DiagnosisContextManager.create("ses_1", "goal")
    resolver = ParameterResolver()

    result = await resolver.resolve_for_step(
        context,
        step({"properties": {"rank": {"type": "integer"}}, "required": ["rank"]}),
        current_user_input={"rank": "3"},
    )

    assert result.arguments == {"rank": "3"}
    assert result.missing_required == []
