from typing import Any, List, Optional
from .base import BaseWorkerAgent, AgentResult
from ...adapters.rag_client import RAGClient
from ...storage.session_store import SessionStore
from ...models.evidence import CreateEvidenceRequest, EvidenceConfidence, EvidenceType, RAGEvidenceMetadata

class KnowledgeAgent(BaseWorkerAgent):
    """Agent specialized in RAG retrieval and knowledge-based QA."""

    def __init__(self, rag_client: RAGClient, session_store: SessionStore):
        self.rag_client = rag_client
        self.session_store = session_store

    async def run(self, session_id: str, plan_step_id: str, goal: str, blackboard: dict) -> AgentResult:
        """Execute RAG retrieval and save evidence."""
        evidence_ids = []
        try:
            result = await self.rag_client.retrieve(goal)
            
            if not result.results:
                evidence = self.session_store.create_evidence(CreateEvidenceRequest(
                    session_id=session_id,
                    step_id=plan_step_id,
                    type=EvidenceType.RAG_EVIDENCE,
                    source="ms_rag",
                    content="未检索到相关知识依据。",
                    summary="未检索到相关知识依据。",
                    confidence=EvidenceConfidence.LOW,
                    metadata={"query": goal, "result_count": 0}
                ))
                evidence_ids.append(evidence.id)
                return AgentResult(status="completed", evidence_ids=evidence_ids)

            for index, item in enumerate(result.results, start=1):
                metadata = RAGEvidenceMetadata(
                    query=result.query,
                    score=item.score,
                    doc_id=item.source.get("doc_id"),
                    chunk_id=item.source.get("chunk_id") or item.metadata.get("chunk_id"),
                    title=item.source.get("title") or item.metadata.get("title"),
                    section_title=item.source.get("section_title") or item.metadata.get("section_title"),
                    path=item.source.get("path") or item.metadata.get("path"),
                    url=item.source.get("url") or item.metadata.get("url"),
                    vector_score=item.metadata.get("vector_score"),
                    keyword_score=item.metadata.get("keyword_score"),
                    final_score=item.metadata.get("final_score"),
                    rank=index,
                    raw={"item": item.raw, "source": item.source, "metadata": item.metadata},
                )
                evidence = self.session_store.create_evidence(CreateEvidenceRequest(
                    session_id=session_id,
                    step_id=plan_step_id,
                    type=EvidenceType.RAG_EVIDENCE,
                    source="ms_rag",
                    content=item.content,
                    summary=item.content[:300],
                    confidence=EvidenceConfidence.MEDIUM,
                    metadata=metadata.model_dump(),
                ))
                evidence_ids.append(evidence.id)
            
            return AgentResult(status="completed", evidence_ids=evidence_ids)

        except Exception as exc:
            evidence = self.session_store.create_evidence(CreateEvidenceRequest(
                session_id=session_id,
                step_id=plan_step_id,
                type=EvidenceType.SYSTEM_EVENT,
                source="rag_client",
                content=str(exc),
                summary="RAG 服务不可用",
                confidence=EvidenceConfidence.HIGH,
                metadata={"code": "RAG_UNAVAILABLE"},
            ))
            return AgentResult(
                status="failed",
                evidence_ids=[evidence.id],
                error_msg=str(exc)
            )

    async def resume(self, session_id: str, plan_step_id: str, user_input: Any, suspended_metadata: dict) -> AgentResult:
        """Resume not supported for KnowledgeAgent as it doesn't suspend."""
        raise NotImplementedError("KnowledgeAgent does not support resume.")
