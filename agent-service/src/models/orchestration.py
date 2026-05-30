"""Orchestration contracts for the Agent Harness."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    CHAT = "chat"
    KNOWLEDGE_QA = "knowledge_qa"
    KNOWLEDGE_RETRIEVE = "knowledge_retrieve"
    DIAGNOSIS = "diagnosis"
    PROFILING_ANALYSIS = "profiling_analysis"
    CONTINUE_ANALYSIS = "continue_analysis"
    REPORT_GENERATION = "report_generation"
    FEEDBACK = "feedback"
    CLARIFICATION = "clarification"


class OrchestratorState(str, Enum):
    IDLE = "idle"
    INTENT_DETECTED = "intent_detected"
    RETRIEVING_KNOWLEDGE = "retrieving_knowledge"
    SEARCHING_PLAYBOOK = "searching_playbook"
    WAITING_USER_INPUT = "waiting_user_input"
    EXECUTING_MCP = "executing_mcp"
    ANALYZING = "analyzing"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"


class IntentDecision(BaseModel):
    intent: IntentType
    confidence: float = 0.0
    reason: str = ""
    extracted: Dict[str, Any] = Field(default_factory=dict)


class PendingInputOption(BaseModel):
    label: str
    value: str
    description: str = ""


class PendingInput(BaseModel):
    id: str
    session_id: str
    plan_id: Optional[str] = None
    step_id: Optional[str] = None
    input_type: Literal["text", "choice", "path", "confirm", "params"]
    question: str
    reason: str = ""
    options: List[PendingInputOption] = Field(default_factory=list)
    recommended_value: Optional[str] = None
    status: Literal["pending", "resolved", "cancelled"] = "pending"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


class ExecutionPlanStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExecutionStepType(str, Enum):
    CHAT_RESPONSE = "chat_response"
    RAG_QA = "rag_qa"
    RAG_RETRIEVE = "rag_retrieve"
    MCP_SEARCH = "mcp_search"
    MCP_EXECUTE = "mcp_execute"
    USER_INPUT = "user_input"
    EVIDENCE_FUSION = "evidence_fusion"
    REPORT_GENERATION = "report_generation"
    FALLBACK_DECISION = "fallback_decision"
    ANSWER_RESPONSE = "answer_response"
    LOAD_SESSION_EVIDENCE = "load_session_evidence"


class ExecutionStep(BaseModel):
    id: str
    plan_id: str
    session_id: str
    type: ExecutionStepType
    name: str
    status: ExecutionStepStatus = ExecutionStepStatus.PENDING
    input: Dict[str, Any] = Field(default_factory=dict)
    output: Optional[Dict[str, Any]] = None
    evidence_ids: List[str] = Field(default_factory=list)
    error: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    elapsed_ms: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ExecutionPlan(BaseModel):
    id: str
    session_id: str
    user_message_id: Optional[str] = None
    intent: IntentType
    status: ExecutionPlanStatus = ExecutionPlanStatus.PENDING
    goal: str = ""
    steps: List[ExecutionStep] = Field(default_factory=list)
    current_step_id: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AutoExecutionDecision(BaseModel):
    action: Literal["continue_auto", "require_user_input", "stop_and_summarize", "fail"]
    reason: str
    pending_input: Optional[PendingInput] = None


class MCPNextStep(BaseModel):
    tool_name: Optional[str] = None
    action: Optional[str] = None
    schema_: Dict[str, Any] = Field(default_factory=dict, alias="schema")
    progress: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class MCPToolResult(BaseModel):
    status: str
    tool_name: Optional[str] = None
    text: str = ""
    next_step: Optional[MCPNextStep] = None
    requires_user_input: bool = False
    error: Optional[str] = None
    elapsed_ms: Optional[int] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class MCPSearchResult(BaseModel):
    status: str
    text: str = ""
    playbook_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    auto_selected_playbook: Optional[str] = None
    selected_playbook: Optional[str] = None
    initial_step: Optional[MCPNextStep] = None
    suggested_arguments: Dict[str, Any] = Field(default_factory=dict)
    requires_user_choice: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: Optional[int] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class LLMQueryRewriteResult(BaseModel):
    rewritten_query: str = ""
    rationale: Optional[str] = None


class LLMPlaybookRecommendation(BaseModel):
    playbook_id: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: Optional[str] = None


class LLMPlaybookRecommendationResult(BaseModel):
    recommendations: List[LLMPlaybookRecommendation] = Field(default_factory=list)


class LLMPlaybookSelectionResult(BaseModel):
    select_playbook: Optional[str] = None
    query: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: Optional[str] = None


class LLMParameterExtractionResult(BaseModel):
    parameters: Dict[str, Any] = Field(default_factory=dict)
    missing_required: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class LLMEvidenceSummaryResult(BaseModel):
    summary: str = ""
    caveats: List[str] = Field(default_factory=list)


class RAGRetrieveItem(BaseModel):
    content: str
    score: Optional[float] = None
    source: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    raw: Dict[str, Any] = Field(default_factory=dict)


class RAGRetrieveResult(BaseModel):
    query: str
    results: List[RAGRetrieveItem] = Field(default_factory=list)
    elapsed_ms: Optional[int] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class SSEEventEnvelope(BaseModel):
    event: str
    event_id: str
    session_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    data: Dict[str, Any] = Field(default_factory=dict)
