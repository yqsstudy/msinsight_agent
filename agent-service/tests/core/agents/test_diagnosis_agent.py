import pytest
from src.core.agents.diagnosis_agent import DiagnosisAgent
from src.core.agents.base import AgentResult

@pytest.mark.asyncio
async def test_diagnosis_agent_suspend_on_missing_path():
    agent = DiagnosisAgent()
    blackboard = {"extracted": {}}
    
    result = await agent.run(
        session_id="test_session",
        plan_step_id="step_1",
        goal="Diagnose the issue",
        blackboard=blackboard
    )
    
    assert result.status == "suspended"
    assert result.requirement is not None
    assert result.requirement.input_type == "path"
    assert result.requirement.metadata["agent_type"] == "diagnosis"
    assert result.requirement.metadata["resume_action"] == "execute_import"

@pytest.mark.asyncio
async def test_diagnosis_agent_completes_with_path():
    agent = DiagnosisAgent()
    blackboard = {"extracted": {"path": "/path/to/diagnose"}}
    
    result = await agent.run(
        session_id="test_session",
        plan_step_id="step_1",
        goal="Diagnose the issue",
        blackboard=blackboard
    )
    
    assert result.status == "completed"

@pytest.mark.asyncio
async def test_diagnosis_agent_saves_schema_on_suspend():
    from src.core.agents.diagnosis_agent import DiagnosisAgent
    from unittest.mock import AsyncMock, MagicMock
    from src.models.orchestration import MCPNextStep, MCPToolResult
    
    # Setup mocks
    mock_gateway = AsyncMock()
    # Return a dummy tool execution that requires the next step
    mock_next_step = MCPNextStep(tool_name="next_tool", schema={"properties": {"param1": {"type": "string"}}, "required": ["param1"]})
    mock_result = MCPToolResult(status="success", text="ok", next_step=mock_next_step)
    mock_gateway.execute_profiler_tool.return_value = mock_result
    
    mock_policy = MagicMock()
    mock_policy_decision = MagicMock()
    mock_policy_decision.action = "continue_auto"
    mock_policy.decide_after_mcp_result.return_value = mock_policy_decision
    
    mock_llm = AsyncMock()
    mock_llm.extract_parameters.return_value = {} # simulates missing param
    
    mock_session_store = MagicMock()
    mock_evidence = MagicMock()
    mock_evidence.id = "mock_id"
    mock_session_store.create_evidence.return_value = mock_evidence
    
    agent = DiagnosisAgent(mock_gateway, mock_session_store, mock_policy, mock_llm)
    
    # Call _execute_tool_and_check_next directly for isolated testing
    result = await agent._execute_tool_and_check_next("ses1", "step1", "tool1", {}, 0, {})
    
    assert result.status == "suspended"
    assert result.requirement is not None
    assert "tool_schema" in result.requirement.metadata
    assert result.requirement.metadata["tool_schema"] == {"properties": {"param1": {"type": "string"}}, "required": ["param1"]}
