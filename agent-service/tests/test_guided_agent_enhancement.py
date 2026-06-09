import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.agents.diagnosis_agent import DiagnosisAgent
from src.core.diagnosis import DiagnosisContextManager, ParameterResolver
from src.core.mcp_llm_assistant import MCPLLMOrchestrationAssistant
from src.models.config import LLMAssistanceConfig
from src.models.orchestration import MCPNextStep


class TimeoutLLMRouter:
    async def chat(self, *args, **kwargs):
        await asyncio.sleep(0.05)
        return {"content": "{}"}


@pytest.mark.asyncio
async def test_llm_timeout_records_failure_summary(caplog):
    assistant = MCPLLMOrchestrationAssistant(
        TimeoutLLMRouter(),
        LLMAssistanceConfig(enabled=True, timeout_seconds=0.01),
    )

    result = await assistant.extract_parameters_by_schema(
        "请选择通信组",
        {"properties": {"groupIdHash": {"type": "string"}}, "required": ["groupIdHash"]},
        {},
        {"tool_name": "communication_duration_slow_rank_list"},
    )

    assert result == {}
    assert assistant.last_failure_summary()["status"] == "timeout"
    assert "timeout_seconds" in caplog.text
    assert "communication_duration_slow_rank_list" in caplog.text


@pytest.mark.asyncio
async def test_parameter_resolver_inherits_iteration_id_before_missing_check():
    context = DiagnosisContextManager.create(
        session_id="ses_test",
        plan_id="plan_test",
        root_message="分析通信问题",
        extracted={"iterationId": "3"},
    )
    step = MCPNextStep(
        tool_name="communication_duration_slow_rank_list",
        schema={
            "properties": {
                "iterationId": {"type": "string"},
                "groupIdHash": {"type": "string"},
            },
            "required": ["iterationId", "groupIdHash"],
        },
    )

    resolution = await ParameterResolver().resolve_for_step(context, step)

    assert resolution.arguments["iterationId"] == "3"
    assert resolution.missing_required == ["groupIdHash"]
    assert "iterationId" in resolution.param_sources


def test_build_suspension_requirement_extracts_group_options():
    agent = DiagnosisAgent(None, None, None, None)
    context = DiagnosisContextManager.create(
        session_id="ses_test",
        plan_id="plan_test",
        root_message="分析通信问题",
        extracted={},
    )
    context.known_params["data"] = [
        {
            "groupIdHash": "mock_group_hash",
            "pgName": "mock_pg",
            "duration": 120.5,
            "rankList": ["0", "1"],
        }
    ]

    requirement = agent._build_suspension_requirement(
        ["groupIdHash"],
        "communication_duration_slow_rank_list",
        context,
        {"tool_schema": {"properties": {"groupIdHash": {"type": "string"}}}},
    )

    field = requirement.metadata["fields"][0]
    assert field["type"] == "select"
    assert field["options"][0]["value"] == "mock_group_hash"
    assert "mock_pg" in field["options"][0]["label"]
    assert requirement.options == field["options"]


def test_single_group_option_autofill_updates_resolution():
    agent = DiagnosisAgent(None, None, None, None)
    context = DiagnosisContextManager.create(
        session_id="ses_test",
        plan_id="plan_test",
        root_message="分析通信问题",
        extracted={},
    )
    context.known_params["data"] = [{"groupIdHash": "only_group", "pgName": "pg0"}]
    step = MCPNextStep(
        tool_name="communication_duration_slow_rank_list",
        schema={
            "properties": {
                "iterationId": {"type": "string"},
                "groupIdHash": {"type": "string"},
            },
            "required": ["iterationId", "groupIdHash"],
        },
    )

    from src.core.diagnosis.models import ParameterResolutionResult

    resolution = ParameterResolutionResult(
        arguments={"iterationId": "3"},
        missing_required=["groupIdHash"],
    )
    updated = agent._apply_single_option_autofill(resolution, step, context, {"tool_schema": step.schema_})

    assert updated.arguments["groupIdHash"] == "only_group"
    assert updated.missing_required == []
    assert updated.param_sources["groupIdHash"]["source"] == "auto_selected_single_option"
