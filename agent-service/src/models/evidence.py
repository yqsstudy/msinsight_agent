"""Evidence data models for auditable agent decisions."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EvidenceType(str, Enum):
    RAG_EVIDENCE = "rag_evidence"
    MCP_OBSERVATION = "mcp_observation"
    USER_INPUT = "user_input"
    AGENT_CONCLUSION = "agent_conclusion"
    SYSTEM_EVENT = "system_event"


class EvidenceConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class Evidence(BaseModel):
    id: str
    session_id: str
    plan_id: Optional[str] = None
    step_id: Optional[str] = None
    type: EvidenceType
    source: str
    content: str
    summary: Optional[str] = None
    confidence: EvidenceConfidence = EvidenceConfidence.UNKNOWN
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CreateEvidenceRequest(BaseModel):
    session_id: str
    plan_id: Optional[str] = None
    step_id: Optional[str] = None
    type: EvidenceType
    source: str
    content: str
    summary: Optional[str] = None
    confidence: EvidenceConfidence = EvidenceConfidence.UNKNOWN
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RAGEvidenceMetadata(BaseModel):
    query: str
    score: Optional[float] = None
    doc_id: Optional[str] = None
    chunk_id: Optional[str] = None
    title: Optional[str] = None
    section_title: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    vector_score: Optional[float] = None
    keyword_score: Optional[float] = None
    final_score: Optional[float] = None
    rank: Optional[int] = None
    retriever: str = "ms_rag.retrieve"
    raw: Dict[str, Any] = Field(default_factory=dict)


class MCPObservationMetadata(BaseModel):
    mcp_tool: str
    internal_tool: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)
    playbook_id: Optional[str] = None
    step: Optional[int] = None
    progress: Dict[str, Any] = Field(default_factory=dict)
    next_step: Optional[Dict[str, Any]] = None
    elapsed_ms: Optional[int] = None
    status: str = "unknown"
    raw: Dict[str, Any] = Field(default_factory=dict)
