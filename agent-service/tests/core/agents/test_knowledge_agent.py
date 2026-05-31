import os
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.core.agents.knowledge_agent import KnowledgeAgent
from src.adapters.rag_client import RAGClient
from src.storage.session_store import SessionStore
from src.models.evidence import EvidenceType, EvidenceConfidence

@pytest.mark.asyncio
async def test_knowledge_agent_run_success():
    # Setup
    rag_client = AsyncMock(spec=RAGClient)
    session_store = MagicMock(spec=SessionStore)
    
    # Mock RAG response
    mock_result = MagicMock()
    mock_item = MagicMock()
    mock_item.content = "Knowledge content"
    mock_item.score = 0.9
    mock_item.source = {"title": "Test Doc", "doc_id": "doc_1"}
    mock_item.metadata = {"chunk_id": "chunk_1"}
    mock_item.raw = {"raw_field": "val"}
    mock_result.results = [mock_item]
    mock_result.query = "test query"
    mock_result.elapsed_ms = 100
    
    rag_client.retrieve.return_value = mock_result
    
    # Mock session_store.create_evidence
    mock_evidence = MagicMock()
    mock_evidence.id = "ev_123"
    session_store.create_evidence.return_value = mock_evidence
    
    agent = KnowledgeAgent(rag_client=rag_client, session_store=session_store)
    
    # Execute
    result = await agent.run(
        session_id="ses_1",
        plan_step_id="step_1",
        goal="Find info about X",
        blackboard={}
    )
    
    # Assert
    assert result.status == "completed"
    assert "ev_123" in result.evidence_ids
    rag_client.retrieve.assert_called_once_with("Find info about X")
    assert session_store.create_evidence.call_count == 1
    
    # Verify evidence creation arguments
    args, _ = session_store.create_evidence.call_args
    req = args[0]
    assert req.session_id == "ses_1"
    assert req.plan_id is None # Or should it be linked to plan? Orchestrator usually provides it.
    assert req.type == EvidenceType.RAG_EVIDENCE
    assert req.source == "ms_rag"
    assert req.content == "Knowledge content"
    assert req.confidence == EvidenceConfidence.MEDIUM

@pytest.mark.asyncio
async def test_knowledge_agent_run_no_results():
    rag_client = AsyncMock(spec=RAGClient)
    session_store = MagicMock(spec=SessionStore)
    
    mock_result = MagicMock()
    mock_result.results = []
    mock_result.query = "test query"
    rag_client.retrieve.return_value = mock_result
    
    mock_evidence = MagicMock()
    mock_evidence.id = "ev_empty"
    session_store.create_evidence.return_value = mock_evidence
    
    agent = KnowledgeAgent(rag_client=rag_client, session_store=session_store)
    
    result = await agent.run("ses_1", "step_1", "query", {})
    
    assert result.status == "completed"
    assert "ev_empty" in result.evidence_ids
    assert session_store.create_evidence.call_count == 1
    
    args, _ = session_store.create_evidence.call_args
    req = args[0]
    assert req.content == "未检索到相关知识依据。"

@pytest.mark.asyncio
async def test_knowledge_agent_run_error():
    rag_client = AsyncMock(spec=RAGClient)
    session_store = MagicMock(spec=SessionStore)
    
    rag_client.retrieve.side_effect = Exception("RAG service down")
    
    mock_evidence = MagicMock()
    mock_evidence.id = "ev_error"
    session_store.create_evidence.return_value = mock_evidence
    
    agent = KnowledgeAgent(rag_client=rag_client, session_store=session_store)
    
    result = await agent.run("ses_1", "step_1", "query", {})
    
    assert result.status == "failed"
    assert result.error_msg == "RAG service down"
    assert "ev_error" in result.evidence_ids
    
    args, _ = session_store.create_evidence.call_args
    req = args[0]
    assert req.type == EvidenceType.SYSTEM_EVENT
    assert req.content == "RAG service down"
