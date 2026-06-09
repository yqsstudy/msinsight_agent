import pytest
from unittest.mock import AsyncMock, MagicMock
from src.core.agents.diagnosis_agent import DiagnosisAgent
from src.core.agents.base import AgentResult
from src.models.orchestration import MCPNextStep, MCPToolResult, MCPSearchResult

@pytest.fixture
def mock_dependencies():
    return {
        "mcp_gateway": AsyncMock(),
        "session_store": MagicMock(),
        "policy": MagicMock(),
        "llm_assistant": AsyncMock(),
    }

@pytest.mark.asyncio
async def test_diagnosis_agent_run_suspends_on_user_choice(mock_dependencies):
    # Setup mocks
    mock_gateway = mock_dependencies["mcp_gateway"]
    mock_gateway.ensure_tools_loaded.return_value = []
    
    mock_search_result = MagicMock(spec=MCPSearchResult)
    mock_search_result.requires_user_choice = True
    mock_search_result.playbook_candidates = [{"id": "pb1", "name": "Playbook 1"}]
    mock_search_result.text = "Multiple choices found"
    mock_search_result.auto_selected_playbook = None
    mock_search_result.selected_playbook = None
    mock_search_result.initial_step = None
    mock_search_result.suggested_arguments = {}
    mock_search_result.elapsed_ms = 50
    mock_search_result.raw = {}
    mock_gateway.search_profiler_tools.return_value = mock_search_result
    
    mock_llm = mock_dependencies["llm_assistant"]
    mock_llm.select_playbook_from_tools.return_value = {"query": "test query"}
    mock_llm.recommend_playbook_candidate.return_value = [{"id": "pb1", "name": "Playbook 1"}]
    
    mock_session_store = mock_dependencies["session_store"]
    mock_evidence = MagicMock()
    mock_evidence.id = "ev1"
    mock_session_store.create_evidence.return_value = mock_evidence
    
    mock_context = MagicMock()
    mock_dependencies["session_store"].get_diagnosis_context.return_value = mock_context

    agent = DiagnosisAgent(
        mock_dependencies["mcp_gateway"],
        mock_dependencies["session_store"],
        mock_dependencies["policy"],
        mock_dependencies["llm_assistant"]
    )
    
    result = await agent.run("session1", "step1", "goal", {"extracted": {}})
    
    print(result.error_msg); assert result.status == "suspended"
    assert result.requirement.input_type == "choice"
    assert "ev1" in result.evidence_ids

@pytest.mark.asyncio
async def test_diagnosis_agent_execute_tool_and_check_next_metadata(mock_dependencies):
    # Setup mocks
    mock_gateway = mock_dependencies["mcp_gateway"]
    mock_next_step = MCPNextStep(
        tool_name="next_tool", 
        schema_={"properties": {"param1": {"type": "string"}}, "required": ["param1"]}
    )
    mock_result = MCPToolResult(
        status="success", 
        text="execution result", 
        next_step=mock_next_step,
        elapsed_ms=100,
        raw={"raw_data": "val"}
    )
    mock_gateway.execute_profiler_tool.return_value = mock_result
    
    mock_policy = mock_dependencies["policy"]
    mock_policy_decision = MagicMock()
    mock_policy_decision.action = "continue_auto"
    mock_policy.decide_after_mcp_result.return_value = mock_policy_decision
    
    mock_llm = mock_dependencies["llm_assistant"]
    mock_llm.extract_parameters_by_schema.return_value = {} # simulates missing param
    
    mock_session_store = mock_dependencies["session_store"]
    mock_evidence = MagicMock()
    mock_evidence.id = "ev2"
    mock_session_store.create_evidence.return_value = mock_evidence
    
    mock_context = MagicMock()
    mock_dependencies["session_store"].get_diagnosis_context.return_value = mock_context

    agent = DiagnosisAgent(
        mock_dependencies["mcp_gateway"],
        mock_dependencies["session_store"],
        mock_dependencies["policy"],
        mock_dependencies["llm_assistant"]
    )
    
    mock_context = MagicMock()
    mock_context.diagnosis_id = "test_id"
    mock_context.revision = 1
    mock_context.known_params = {}
    mock_context.completed_steps = []
    
    # Test tool execution and metadata population
    result = await agent._execute_tool_and_check_next("ses1", "step1", "tool1", {"arg1": "val1"}, 0, mock_context)
    
    assert result.status == "suspended"
    assert "tool_schema" in result.requirement.metadata
    
    # Verify evidence creation metadata
    args, kwargs = mock_session_store.create_evidence.call_args
    evidence_request = args[0]
    assert evidence_request.metadata["mcp_tool"] == "execute_profiler_tool"
    assert evidence_request.metadata["internal_tool"] == "tool1"
    assert evidence_request.metadata["arguments"] == {"arg1": "val1"}
    assert evidence_request.metadata["elapsed_ms"] == 100

@pytest.mark.asyncio
async def test_diagnosis_agent_resume_with_args(mock_dependencies):
    mock_context = MagicMock()
    mock_dependencies["session_store"].get_diagnosis_context.return_value = mock_context

    agent = DiagnosisAgent(
        mock_dependencies["mcp_gateway"],
        mock_dependencies["session_store"],
        mock_dependencies["policy"],
        mock_dependencies["llm_assistant"]
    )
    
    # Mock _execute_tool_and_check_next to avoid deep mocking
    agent._execute_tool_and_check_next = AsyncMock()
    agent._execute_tool_and_check_next.return_value = AgentResult(status="completed", evidence_ids=["ev3"])
    
    suspended_metadata = {
        "resume_action": "continue_mcp_with_args",
        "tool_name": "target_tool",
        "resolved_arguments": {"existing": "val"},
        "required": ["file_path"],
        "tool_schema": {"properties": {"existing": {"type": "string"}, "file_path": {"type": "string"}}},
        "context": {"extracted": {}},
        "diagnosis_id": "test_id"
    }
    
    result = await agent.resume("session1", "step1", "/tmp/log", suspended_metadata)
    
    assert result.status == "completed"
    agent._execute_tool_and_check_next.assert_called_once()
    call_args = agent._execute_tool_and_check_next.call_args[0]
    assert call_args[2] == "target_tool"
    assert call_args[3]["file_path"] == "/tmp/log"
    assert call_args[3]["existing"] == "val"

@pytest.mark.asyncio
async def test_diagnosis_agent_resume_hybrid_funnel():
    from src.core.agents.diagnosis_agent import DiagnosisAgent
    from unittest.mock import AsyncMock, MagicMock
    
    mock_llm = AsyncMock()
    mock_llm.extract_parameters_by_schema.return_value = {"complex_param": "extracted_value"}
    
    mock_session_store = MagicMock()
    mock_context = MagicMock()
    mock_session_store.get_diagnosis_context.return_value = mock_context
    agent = DiagnosisAgent(AsyncMock(), mock_session_store, MagicMock(), mock_llm)
    agent._execute_tool_and_check_next = AsyncMock(return_value=MagicMock(status="completed"))
    
    # Test 1: Fast Path (single missing parameter, simple input)
    fast_metadata = {
        "resume_action": "continue_mcp_with_args",
        "tool_name": "tool_a",
        "required": ["simple_id"],
        "resolved_arguments": {},
        "tool_schema": {"properties": {"simple_id": {"type": "string"}}},
        "context": {},
        "diagnosis_id": "test_id"
    }
    result = await agent.resume("s1", "step1", "123", fast_metadata)
    print(result.error_msg)
    # Check that LLM wasn't called and execute received the fast mapped arg
    mock_llm.extract_parameters_by_schema.assert_not_called()
    called_args = agent._execute_tool_and_check_next.call_args[0][3]
    assert called_args == {"simple_id": "123"}
    
    # Test 2: Deep Path (complex sentence)
    agent._execute_tool_and_check_next.reset_mock()
    deep_metadata = {
        "resume_action": "continue_mcp_with_args",
        "tool_name": "tool_b",
        "required": ["complex_param"],
        "resolved_arguments": {},
        "tool_schema": {"properties": {"complex_param": {"type": "string"}}},
        "context": {},
        "diagnosis_id": "test_id"
    }
    await agent.resume("s1", "step1", "帮我查一下复杂参数是提取值的那个", deep_metadata)
    # Check that LLM was called
    mock_llm.extract_parameters_by_schema.assert_called_once()
    called_args = agent._execute_tool_and_check_next.call_args[0][3]
    assert called_args == {"complex_param": "extracted_value"}

@pytest.mark.asyncio
async def test_diagnosis_agent_resume_structured_input(mock_dependencies):
    mock_context = MagicMock()
    mock_dependencies["session_store"].get_diagnosis_context.return_value = mock_context

    agent = DiagnosisAgent(
        mock_dependencies["mcp_gateway"],
        mock_dependencies["session_store"],
        mock_dependencies["policy"],
        mock_dependencies["llm_assistant"]
    )
    
    # Mock _execute_tool_and_check_next to avoid deep mocking
    agent._execute_tool_and_check_next = AsyncMock()
    agent._execute_tool_and_check_next.return_value = AgentResult(status="completed")
    
    suspended_metadata = {
        "resume_action": "continue_mcp_with_args",
        "tool_name": "target_tool",
        "resolved_arguments": {"existing": "val"},
        "required": ["param1"],
        "tool_schema": {"properties": {"existing": {"type": "string"}, "param1": {"type": "string"}}},
        "context": {},
        "diagnosis_id": "test_id"
    }
    
    # Case 1: Input as dict
    user_input_dict = {"param1": "value1", "extra": "ignored_if_not_in_schema"}
    await agent.resume("s1", "step1", user_input_dict, suspended_metadata)
    
    # Verify cleaning logic (extra should be removed)
    called_args = agent._execute_tool_and_check_next.call_args[0][3]
    assert called_args == {"param1": "value1", "existing": "val"}
    assert "extra" not in called_args
    mock_dependencies["llm_assistant"].extract_parameters_by_schema.assert_not_called()

    # Case 2: Input as JSON string
    import json
    agent._execute_tool_and_check_next.reset_mock()
    user_input_json = json.dumps({"param1": "value2"})
    await agent.resume("s1", "step1", user_input_json, suspended_metadata)
    called_args = agent._execute_tool_and_check_next.call_args[0][3]
    assert called_args == {"existing": "val", "param1": "value2"}
    mock_dependencies["llm_assistant"].extract_parameters_by_schema.assert_not_called()

@pytest.mark.asyncio
async def test_diagnosis_agent_auto_continue_sanitization(mock_dependencies):
    # Setup mocks for auto-continuation
    mock_gateway = mock_dependencies["mcp_gateway"]
    
    # Step 1 result triggers auto-continue to Step 2
    mock_next_step = MCPNextStep(
        tool_name="next_tool", 
        schema_={"properties": {"param2": {"type": "string"}}, "required": ["param2"]}
    )
    mock_result1 = MCPToolResult(
        status="success", 
        text="step 1 ok", 
        next_step=mock_next_step,
        elapsed_ms=50,
        raw={}
    )
    
    # Step 2 result (to terminate recursion)
    mock_result2 = MCPToolResult(
        status="success", 
        text="step 2 ok", 
        next_step=None,
        elapsed_ms=50,
        raw={}
    )
    
    mock_gateway.execute_profiler_tool.side_effect = [mock_result1, mock_result2]
    
    mock_policy = mock_dependencies["policy"]
    mock_policy_decision = MagicMock()
    mock_policy_decision.action = "continue_auto"
    mock_policy.decide_after_mcp_result.return_value = mock_policy_decision
    
    mock_llm = mock_dependencies["llm_assistant"]
    # Return arguments including an "extra" one not in schema
    mock_llm.extract_parameters.return_value = {"param2": "val2", "dirty_extra": "bad"} 
    
    mock_session_store = mock_dependencies["session_store"]
    mock_evidence = MagicMock()
    mock_evidence.id = "ev_id"
    mock_session_store.create_evidence.return_value = mock_evidence
    
    mock_context = MagicMock()
    mock_dependencies["session_store"].get_diagnosis_context.return_value = mock_context

    agent = DiagnosisAgent(
        mock_dependencies["mcp_gateway"],
        mock_dependencies["session_store"],
        mock_dependencies["policy"],
        mock_dependencies["llm_assistant"]
    )
    
    mock_context = MagicMock()
    mock_context.diagnosis_id = "test_id"
    mock_context.revision = 1
    mock_context.known_params = {}
    mock_context.completed_steps = []
    
    await agent._execute_tool_and_check_next("ses1", "step1", "tool1", {"arg1": "val1"}, 0, mock_context)
    
    # Verify the second call (auto-continued one) was sanitized
    # First call: tool1, {"arg1": "val1"}
    # Second call: next_tool, {"param2": "val2"} (dirty_extra removed)
    assert mock_gateway.execute_profiler_tool.call_count == 2
    second_call_args = mock_gateway.execute_profiler_tool.call_args_list[1][0]
    assert second_call_args[0] == "next_tool"
    assert second_call_args[1] == {"param2": "val2"}
    assert "dirty_extra" not in second_call_args[1]

