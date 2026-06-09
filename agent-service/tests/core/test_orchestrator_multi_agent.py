import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from src.core.orchestrator import Orchestrator
from src.core.agents.base import AgentResult, AgentRequirement
from src.models.orchestration import IntentType, ExecutionPlanStatus, OrchestratorState

@pytest.mark.asyncio
async def test_orchestrator_signal_router():
    orchestrator = Orchestrator()
    orchestrator.intent_router = MagicMock()
    
    mock_intent = MagicMock()
    mock_intent.intent = IntentType.DIAGNOSIS
    mock_intent.extracted = {}
    mock_intent.reason = "test reason"
    mock_intent.confidence = 1.0
    mock_intent.model_dump.return_value = {"intent": "diagnosis", "confidence": 1.0, "reason": "test reason", "extracted": {}}
    orchestrator.intent_router.route.return_value = mock_intent
    
    # Mock the DiagnosisAgent to return suspended
    mock_agent = AsyncMock()
    req = AgentRequirement(
        input_type="path", 
        question="Path?", 
        metadata={"agent_type": "diagnosis", "resume_action": "execute_import"}
    )
    mock_agent.run.return_value = AgentResult(status="suspended", requirement=req)
    orchestrator.agents["diagnosis"] = mock_agent
    
    # Run handle_message
    session_id = f"ses_{uuid.uuid4().hex}"
    events = [e async for e in orchestrator.handle_message(session_id, "analyze")]
    
    # Verify user_input_required event was emitted
    user_input_events = [e for e in events if e.event == "user_input_required"]
    assert len(user_input_events) == 1
    assert user_input_events[0].data["input_type"] == "path"
    
    # Now simulate resume
    mock_agent.resume.return_value = AgentResult(status="completed", evidence_ids=["ev_1"])
    
    # Create a dummy pending input in the mock session store
    pending_mock = MagicMock(
        id="p1", 
        plan_id="plan1",
        metadata={"agent_type": "diagnosis", "resume_action": "execute_import"}
    )
    orchestrator.session_store.get_active_pending_input = MagicMock(return_value=pending_mock)
    orchestrator.session_store.resolve_pending_input = MagicMock()
    
    resume_events = [e async for e in orchestrator.continue_with_input(session_id, "D:/data/prof")]
    
    mock_agent.resume.assert_called_once()
    assert mock_agent.resume.call_args[0][2] == "D:/data/prof" # user_input is 3rd arg
    
    message_end = [e for e in resume_events if e.event == "message_end"]
    assert len(message_end) == 1
    assert message_end[0].data["state"] == OrchestratorState.COMPLETED.value
