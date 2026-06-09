"""Data contracts for diagnosis-level context management."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DiagnosisStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class ParamSource(str, Enum):
    USER_INITIAL = "user_initial"
    USER_RESUME = "user_resume"
    USER_SELECTION = "user_selection"
    MCP_OUTPUT = "mcp_output"
    MCP_SUGGESTED_ARGUMENT = "mcp_suggested_argument"
    BLACKBOARD_EXTRACTED = "blackboard_extracted"
    LLM_EXTRACTION = "llm_extraction"
    TRANSFERRED = "transferred"
    SYSTEM_DEFAULT = "system_default"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StepStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"


class CandidateSetType(str, Enum):
    PLAYBOOK = "playbook"
    ITERATION = "iteration"
    RANK = "rank"
    OPERATOR = "operator"
    TEMPLATE = "template"
    BRANCH = "branch"
    OTHER = "other"


class CandidateSetStatus(str, Enum):
    ACTIVE = "active"
    SELECTED = "selected"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"


class OperationType(str, Enum):
    ANSWER_PENDING = "answer_pending"
    ROLLBACK = "rollback"
    PAUSE = "pause"
    RESTART = "restart"
    RESUME_PAUSED = "resume_paused"
    CANCEL = "cancel"
    SWITCH_PLAYBOOK = "switch_playbook"
    GENERATE_REPORT = "generate_report"


class OperationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STALE = "stale"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ReconciliationStatus(str, Enum):
    IDLE = "idle"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUSPENDED = "suspended"


class ConflictSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    REQUIRES_INVALIDATION = "requires_invalidation"


class PendingInputIntentType(str, Enum):
    ANSWER_PENDING = "answer_pending"
    MODIFY_PREVIOUS_STEP = "modify_previous_step"
    PAUSE_DIAGNOSIS = "pause_diagnosis"
    RESTART_DIAGNOSIS = "restart_diagnosis"
    RESUME_PAUSED = "resume_paused"
    CANCEL_DIAGNOSIS = "cancel_diagnosis"
    SWITCH_TOPIC_OR_CHAT = "switch_topic_or_chat"
    ASK_STATUS = "ask_status"
    UNCLEAR = "unclear"


class StrictModel(BaseModel):
    """Base model that remains forward-compatible with persisted JSON."""

    model_config = ConfigDict(use_enum_values=True, populate_by_name=True, extra="ignore")


class ParamProvenance(StrictModel):
    key: str
    source: ParamSource | str
    confidence: ConfidenceLevel | str = ConfidenceLevel.MEDIUM
    source_step_index: Optional[int] = None
    source_tool_name: Optional[str] = None
    source_evidence_id: Optional[str] = None
    user_confirmed: bool = False
    revision_created: int = 0
    revision_invalidated: Optional[int] = None
    invalidated: bool = False


class StepRecord(StrictModel):
    step_id: str
    step_index: int
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    argument_sources: Dict[str, str] = Field(default_factory=dict)
    result_summary: Dict[str, Any] = Field(default_factory=dict)
    evidence_id: Optional[str] = None
    next_step: Optional[Dict[str, Any]] = None
    status: StepStatus | str = StepStatus.COMPLETED
    produced_params: List[str] = Field(default_factory=list)
    depends_on_params: List[str] = Field(default_factory=list)
    revision_created: int = 0
    revision_invalidated: Optional[int] = None
    invalidation_reason: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: datetime = Field(default_factory=datetime.utcnow)
    elapsed_ms: Optional[int] = None


class PendingStepState(StrictModel):
    pending_id: str
    resume_action: str
    tool_name: Optional[str] = None
    tool_schema: Dict[str, Any] = Field(default_factory=dict)
    tool_schema_hash: Optional[str] = None
    resolved_arguments: Dict[str, Any] = Field(default_factory=dict)
    required_missing: List[str] = Field(default_factory=list)
    auto_step_count: int = 0
    reason: str = ""
    candidate_set_id: Optional[str] = None
    created_revision: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CandidateItem(StrictModel):
    global_index: int
    value: Any
    label: str
    description: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CandidateSet(StrictModel):
    candidate_set_id: str
    type: CandidateSetType | str = CandidateSetType.OTHER
    source_step_index: Optional[int] = None
    source_tool_name: Optional[str] = None
    source_evidence_id: Optional[str] = None
    status: CandidateSetStatus | str = CandidateSetStatus.ACTIVE
    candidates: List[CandidateItem] = Field(default_factory=list)
    selected_value: Any = None
    created_revision: int = 0
    invalidated_revision: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("candidates")
    @classmethod
    def _candidate_indices_must_be_unique(cls, candidates: List[CandidateItem]) -> List[CandidateItem]:
        indices = [item.global_index for item in candidates]
        if len(indices) != len(set(indices)):
            raise ValueError("candidate global_index values must be unique within a CandidateSet")
        return candidates


class ReconciliationState(StrictModel):
    status: ReconciliationStatus | str = ReconciliationStatus.IDLE
    current_reason: Optional[str] = None
    consecutive_attempts: int = 0
    attempts_by_reason: Dict[str, int] = Field(default_factory=dict)
    last_error: Optional[str] = None
    updated_at: Optional[datetime] = None


class DiagnosisContext(StrictModel):
    diagnosis_id: str
    session_id: str
    plan_id: Optional[str] = None
    root_message: str
    latest_user_input: Optional[str] = None
    status: DiagnosisStatus | str = DiagnosisStatus.ACTIVE
    selected_playbook: Optional[str] = None
    playbook_name: Optional[str] = None
    current_step_index: Optional[int] = None
    current_tool_name: Optional[str] = None
    known_params: Dict[str, Any] = Field(default_factory=dict)
    param_provenance: Dict[str, ParamProvenance] = Field(default_factory=dict)
    completed_steps: List[StepRecord] = Field(default_factory=list)
    invalidated_steps: List[StepRecord] = Field(default_factory=list)
    candidate_sets: List[CandidateSet] = Field(default_factory=list)
    primary_candidate_set_id: Optional[str] = None
    pending: Optional[PendingStepState] = None
    operation_queue_snapshot: List[str] = Field(default_factory=list)
    effective_evidence_ids: List[str] = Field(default_factory=list)
    invalidated_evidence_ids: List[str] = Field(default_factory=list)
    total_auto_steps: int = 0
    reconciliation_state: ReconciliationState = Field(default_factory=ReconciliationState)
    revision: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("param_provenance", mode="before")
    @classmethod
    def _coerce_param_provenance(cls, value: Any) -> Dict[str, Any]:
        return value or {}

    @field_validator("effective_evidence_ids", "invalidated_evidence_ids", "operation_queue_snapshot")
    @classmethod
    def _dedupe_string_lists(cls, values: List[str]) -> List[str]:
        seen = set()
        result = []
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result


class DiagnosisOperation(StrictModel):
    operation_id: str
    idempotency_key: Optional[str] = None
    session_id: str
    diagnosis_id: Optional[str] = None
    type: OperationType | str
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: OperationStatus | str = OperationStatus.QUEUED
    target_pending_id: Optional[str] = None
    expected_revision: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class DiagnosisAuditEvent(StrictModel):
    id: str
    session_id: str
    diagnosis_id: Optional[str] = None
    event_type: str
    revision: Optional[int] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ResolvedParameter(StrictModel):
    key: str
    value: Any
    source: ParamSource | str
    confidence: ConfidenceLevel | str = ConfidenceLevel.MEDIUM
    user_confirmed: bool = False
    source_step_index: Optional[int] = None
    source_tool_name: Optional[str] = None
    source_evidence_id: Optional[str] = None


class ParameterConflict(StrictModel):
    key: str
    existing_value: Any = None
    new_value: Any = None
    existing_source: Optional[str] = None
    new_source: Optional[str] = None
    severity: ConflictSeverity | str = ConflictSeverity.REQUIRES_CONFIRMATION
    affected_step_index: Optional[int] = None
    reason: str = ""


class ParameterResolutionResult(StrictModel):
    arguments: Dict[str, Any] = Field(default_factory=dict)
    missing_required: List[str] = Field(default_factory=list)
    filled: List[ResolvedParameter] = Field(default_factory=list)
    conflicts: List[ParameterConflict] = Field(default_factory=list)
    needs_confirmation: bool = False
    question_reason: Optional[str] = None
    param_sources: Dict[str, Any] = Field(default_factory=dict)
    llm_assistance: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PendingInputIntent(StrictModel):
    intent: PendingInputIntentType | str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    diagnosis_id: Optional[str] = None
    pending_id: Optional[str] = None
    target_step_index: Optional[int] = None
    extracted: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
