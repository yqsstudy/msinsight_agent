import pytest
from src.core.agents.base import AgentRequirement, AgentResult

def test_agent_requirement_creation():
    req = AgentRequirement(
        input_type="text",
        question="What is the path?",
        metadata={"step_id": "123"}
    )
    assert req.input_type == "text"
    assert req.question == "What is the path?"
    assert req.metadata == {"step_id": "123"}

def test_agent_result_creation():
    req = AgentRequirement(input_type="text", question="Q", metadata={})
    res = AgentResult(status="suspended", requirement=req)
    assert res.status == "suspended"
    assert res.requirement == req
    assert res.evidence_ids == []
