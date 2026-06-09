# Schema-Driven LLM Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the `DiagnosisAgent` parameter extraction logic to use a scalable, schema-driven LLM approach (Hybrid Smart Model) instead of hardcoded rules.

**Architecture:** Implement `extract_parameters_by_schema` in `MCPLLMOrchestrationAssistant` to parse inputs using JSON Schema. Update `DiagnosisAgent` to persist the tool's schema during suspension. Rewrite `DiagnosisAgent.resume` to route inputs through a Fast Path (for structured UI inputs) and a Deep Path (delegating to the LLM Assistant).

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, pytest

---

## File Structure Map
- **Modify:** `agent-service/src/core/mcp_llm_assistant.py` (Add `extract_parameters_by_schema` method)
- **Modify:** `agent-service/src/core/agents/diagnosis_agent.py` (Update `_execute_tool_and_check_next` to save schema, and `resume` to implement the funnel)
- **Modify:** `agent-service/tests/core/test_mcp_llm_assistant.py` (Add tests for new LLM extraction)
- **Modify:** `agent-service/tests/core/agents/test_diagnosis_agent.py` (Update tests for the new resume logic)

---

### Task 1: Enhance MCPLLMOrchestrationAssistant with Schema Extraction

**Files:**
- Modify: `agent-service/src/core/mcp_llm_assistant.py`
- Modify: `agent-service/tests/core/test_mcp_llm_assistant.py`

- [ ] **Step 1: Write the failing test**

```python
# Insert into agent-service/tests/core/test_mcp_llm_assistant.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.core.mcp_llm_assistant import MCPLLMOrchestrationAssistant
from src.models.orchestration import LLMParameterExtractionResult

@pytest.mark.asyncio
async def test_extract_parameters_by_schema():
    mock_router = MagicMock()
    mock_router.chat = AsyncMock()
    # Mock LLM returning JSON matching the schema
    mock_router.chat.return_value = '{"iterationId": "5"}'
    
    assistant = MCPLLMOrchestrationAssistant(mock_router, MagicMock())
    
    schema = {
        "properties": {"iterationId": {"type": "string"}},
        "required": ["iterationId"]
    }
    
    result = await assistant.extract_parameters_by_schema(
        user_input="帮我查一下第五个迭代",
        tool_schema=schema,
        existing_args={"clusterPath": "/data"}
    )
    
    assert result == {"iterationId": "5"}
    mock_router.chat.assert_called_once()
    call_args = mock_router.chat.call_args[0][0]
    assert "帮我查一下第五个迭代" in str(call_args)
    assert "iterationId" in str(call_args)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-service/tests/core/test_mcp_llm_assistant.py::test_extract_parameters_by_schema -v`
Expected: FAIL with "AttributeError: 'MCPLLMOrchestrationAssistant' object has no attribute 'extract_parameters_by_schema'"

- [ ] **Step 3: Write minimal implementation**

```python
# Insert into agent-service/src/core/mcp_llm_assistant.py
# Inside class MCPLLMOrchestrationAssistant:

    async def extract_parameters_by_schema(self, user_input: str, tool_schema: dict, existing_args: dict) -> dict:
        """
        Prompts the LLM to extract parameters from user_input based strictly on the provided JSON Schema.
        Returns a dictionary of newly extracted parameters.
        """
        from ..llm.base import ChatMessage
        
        system_prompt = f"""
You are an expert parameter extraction assistant.
Your task is to extract parameters from the user's input to fulfill the required tool arguments.

TOOL JSON SCHEMA:
{json.dumps(tool_schema, ensure_ascii=False, indent=2)}

ALREADY PROVIDED ARGUMENTS (Do not extract these again unless the user explicitly overrides them):
{json.dumps(existing_args, ensure_ascii=False, indent=2)}

INSTRUCTIONS:
1. Extract values from the user's input that match the properties defined in the TOOL JSON SCHEMA.
2. Return ONLY a valid JSON object containing the extracted key-value pairs.
3. Do not include markdown formatting like ```json or any other text.
4. If no parameters can be extracted, return an empty JSON object: {{}}
"""
        messages = [
            ChatMessage(role="system", content=system_prompt.strip()),
            ChatMessage(role="user", content=user_input)
        ]
        
        try:
            response = await self.llm_router.chat(messages, temperature=0.1)
            text = response.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
            return {}
        except Exception as e:
            # Fallback to empty dict on parsing error
            return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-service/tests/core/test_mcp_llm_assistant.py::test_extract_parameters_by_schema -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-service/src/core/mcp_llm_assistant.py agent-service/tests/core/test_mcp_llm_assistant.py
git commit -m "feat: add schema-driven parameter extraction to LLMAssistant"
```

---

### Task 2: Inject Tool Schema into Suspension Metadata

**Files:**
- Modify: `agent-service/src/core/agents/diagnosis_agent.py`
- Modify: `agent-service/tests/core/agents/test_diagnosis_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# Insert into agent-service/tests/core/agents/test_diagnosis_agent.py
# Modify existing test test_diagnosis_agent_suspend_on_missing_path or add a new one

@pytest.mark.asyncio
async def test_diagnosis_agent_saves_schema_on_suspend():
    from src.core.agents.diagnosis_agent import DiagnosisAgent
    from unittest.mock import AsyncMock, MagicMock
    from src.models.orchestration import MCPNextStep, MCPToolResult
    
    # Setup mocks
    mock_gateway = AsyncMock()
    # Return a dummy tool execution that requires the next step
    mock_next_step = MCPNextStep(tool_name="next_tool", schema={"properties": {"param1": {"type": "string"}}}, required=["param1"])
    mock_result = MCPToolResult(status="success", text="ok", next_step=mock_next_step)
    mock_gateway.execute_profiler_tool.return_value = mock_result
    
    mock_policy = MagicMock()
    mock_policy_decision = MagicMock()
    mock_policy_decision.action = "continue_auto"
    mock_policy.decide_after_mcp_result.return_value = mock_policy_decision
    
    mock_llm = AsyncMock()
    mock_llm.extract_parameters.return_value = {} # simulates missing param
    
    agent = DiagnosisAgent(mock_gateway, MagicMock(), mock_policy, mock_llm)
    
    # Call _execute_tool_and_check_next directly for isolated testing
    result = await agent._execute_tool_and_check_next("ses1", "step1", "tool1", {}, 0, {})
    
    assert result.status == "suspended"
    assert result.requirement is not None
    assert "tool_schema" in result.requirement.metadata
    assert result.requirement.metadata["tool_schema"] == {"properties": {"param1": {"type": "string"}}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-service/tests/core/agents/test_diagnosis_agent.py::test_diagnosis_agent_saves_schema_on_suspend -v`
Expected: FAIL (KeyError or AssertionError for 'tool_schema')

- [ ] **Step 3: Write minimal implementation**

```python
# Modify agent-service/src/core/agents/diagnosis_agent.py
# In `_execute_tool_and_check_next`, around line where `AgentRequirement` is built for missing params:

                missing = self._missing_required_arguments(next_step, next_args)
                if missing:
                    return AgentResult(
                        status="suspended",
                        evidence_ids=[evidence.id],
                        requirement=AgentRequirement(
                            input_type="params",
                            question=f"下一步 `{next_step.tool_name}` 需要参数：{', '.join(missing)}。请补充参数。",
                            metadata={
                                "agent_type": "diagnosis",
                                "resume_action": "continue_mcp_with_args",
                                "tool_name": next_step.tool_name,
                                "required": missing,
                                "resolved_arguments": next_args,
                                "tool_schema": next_step.schema_,  # <--- THIS IS THE FIX
                                "context": context,
                                "auto_step_count": auto_count
                            }
                        )
                    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-service/tests/core/agents/test_diagnosis_agent.py::test_diagnosis_agent_saves_schema_on_suspend -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-service/src/core/agents/diagnosis_agent.py agent-service/tests/core/agents/test_diagnosis_agent.py
git commit -m "fix: persist tool schema in metadata upon suspension"
```

---

### Task 3: Refactor DiagnosisAgent.resume to use Hybrid Funnel

**Files:**
- Modify: `agent-service/src/core/agents/diagnosis_agent.py`
- Modify: `agent-service/tests/core/agents/test_diagnosis_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# Insert into agent-service/tests/core/agents/test_diagnosis_agent.py

@pytest.mark.asyncio
async def test_diagnosis_agent_resume_hybrid_funnel():
    from src.core.agents.diagnosis_agent import DiagnosisAgent
    from unittest.mock import AsyncMock, MagicMock
    
    mock_llm = AsyncMock()
    mock_llm.extract_parameters_by_schema.return_value = {"complex_param": "extracted_value"}
    
    agent = DiagnosisAgent(AsyncMock(), MagicMock(), MagicMock(), mock_llm)
    agent._execute_tool_and_check_next = AsyncMock(return_value=MagicMock(status="completed"))
    
    # Test 1: Fast Path (single missing parameter, simple input)
    fast_metadata = {
        "resume_action": "continue_mcp_with_args",
        "tool_name": "tool_a",
        "required": ["simple_id"],
        "resolved_arguments": {},
        "tool_schema": {"properties": {"simple_id": {"type": "string"}}}
    }
    await agent.resume("s1", "step1", "123", fast_metadata)
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
        "tool_schema": {"properties": {"complex_param": {"type": "string"}}}
    }
    await agent.resume("s1", "step1", "帮我查一下复杂参数是提取值的那个", deep_metadata)
    # Check that LLM was called
    mock_llm.extract_parameters_by_schema.assert_called_once()
    called_args = agent._execute_tool_and_check_next.call_args[0][3]
    assert called_args == {"complex_param": "extracted_value"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-service/tests/core/agents/test_diagnosis_agent.py::test_diagnosis_agent_resume_hybrid_funnel -v`
Expected: FAIL (The current implementation uses regex and does not have the funnel logic)

- [ ] **Step 3: Write minimal implementation**

```python
# Replace the `resume` method in agent-service/src/core/agents/diagnosis_agent.py

    def _is_complex_sentence(self, text: str) -> bool:
        """Heuristic to determine if input is a conversational sentence rather than a raw value."""
        return len(text) > 20 or any(char in text for char in ["，", "。", "！", "？", "帮我", "请", "是什么"])

    async def resume(self, session_id: str, plan_step_id: str, user_input: Any, suspended_metadata: dict) -> AgentResult:
        """Resume execution from a suspended state."""
        resume_action = suspended_metadata.get("resume_action")
        context = suspended_metadata.get("context", {})
        
        if resume_action == "select_playbook":
            # Restart run with the selected playbook merged into context
            blackboard = {
                "extracted": {
                    **context.get("extracted", {}),
                    "selected_playbook": str(user_input).strip()
                }
            }
            return await self.run(session_id, plan_step_id, suspended_metadata.get("original_message", ""), blackboard)
            
        if resume_action == "continue_mcp_with_args":
            tool_name = suspended_metadata.get("tool_name")
            resolved = suspended_metadata.get("resolved_arguments", {})
            required_missing = suspended_metadata.get("required", [])
            tool_schema = suspended_metadata.get("tool_schema", {})
            
            new_args = {}
            
            # --- FUNNEL 1: Fast Path (Structured Input) ---
            if isinstance(user_input, str) and len(required_missing) == 1 and not self._is_complex_sentence(user_input):
                 new_args[required_missing[0]] = user_input.strip()
                 
            # --- FUNNEL 2: Deep Path (LLM Schema Extraction) ---
            if not new_args:
                 new_args = await self.llm_assistant.extract_parameters_by_schema(
                     user_input=str(user_input),
                     tool_schema=tool_schema,
                     existing_args=resolved
                 )
                 
            # Merge and execute
            merged_args = {**resolved, **new_args}
            
            # Clean arguments using schema properties
            allowed_keys = set(tool_schema.get("properties", {}).keys())
            allowed_keys.update({"file_path", "project_name"}) 
            clean_args = {k: v for k, v in merged_args.items() if k in allowed_keys}
            
            auto_count = int(suspended_metadata.get("auto_step_count", 0))
            return await self._execute_tool_and_check_next(session_id, plan_step_id, tool_name, clean_args, auto_count, context)

        return AgentResult(status="failed", error_msg=f"Unknown resume action: {resume_action}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-service/tests/core/agents/test_diagnosis_agent.py::test_diagnosis_agent_resume_hybrid_funnel -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-service/src/core/agents/diagnosis_agent.py agent-service/tests/core/agents/test_diagnosis_agent.py
git commit -m "refactor: implement Hybrid Smart Model funnel for parameter extraction in DiagnosisAgent"
```
