"""DiagnosisContext lifecycle and mutation helpers."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from .models import (
    CandidateSet,
    CandidateSetStatus,
    ConfidenceLevel,
    DiagnosisContext,
    DiagnosisStatus,
    ParamProvenance,
    ParamSource,
    PendingStepState,
    StepRecord,
)


class DiagnosisContextManager:
    """Pure helpers for creating and mutating diagnosis contexts.

    The helpers deliberately avoid database access. Persistence belongs to
    SessionStore; orchestration belongs to DiagnosisAgent/Orchestrator.
    """

    @staticmethod
    def create(
        session_id: str,
        root_message: str,
        plan_id: Optional[str] = None,
        diagnosis_id: Optional[str] = None,
        extracted: Optional[Dict[str, Any]] = None,
    ) -> DiagnosisContext:
        context = DiagnosisContext(
            diagnosis_id=diagnosis_id or f"diag_{uuid.uuid4().hex}",
            session_id=session_id,
            plan_id=plan_id,
            root_message=root_message,
            latest_user_input=root_message,
            status=DiagnosisStatus.ACTIVE,
        )
        for key, value in (extracted or {}).items():
            if value not in (None, ""):
                DiagnosisContextManager.add_or_update_param(
                    context,
                    key=key,
                    value=value,
                    source=ParamSource.BLACKBOARD_EXTRACTED,
                    confidence=ConfidenceLevel.HIGH,
                    increment_revision=False,
                )
        context.updated_at = datetime.utcnow()
        return context

    @staticmethod
    def from_json(payload: str | Dict[str, Any]) -> DiagnosisContext:
        data = json.loads(payload) if isinstance(payload, str) else payload
        return DiagnosisContext.model_validate(data)

    @staticmethod
    def to_json(context: DiagnosisContext) -> str:
        return context.model_dump_json()

    @staticmethod
    def increment_revision(context: DiagnosisContext) -> int:
        context.revision += 1
        context.updated_at = datetime.utcnow()
        return context.revision

    @staticmethod
    def mark_status(context: DiagnosisContext, status: DiagnosisStatus | str) -> None:
        context.status = status
        DiagnosisContextManager.increment_revision(context)

    @staticmethod
    def set_pending(context: DiagnosisContext, pending: PendingStepState) -> None:
        pending.created_revision = context.revision
        context.pending = pending
        DiagnosisContextManager.increment_revision(context)

    @staticmethod
    def clear_pending(context: DiagnosisContext, pending_id: Optional[str] = None) -> bool:
        if context.pending is None:
            return False
        if pending_id and context.pending.pending_id != pending_id:
            return False
        context.pending = None
        DiagnosisContextManager.increment_revision(context)
        return True

    @staticmethod
    def add_or_update_param(
        context: DiagnosisContext,
        key: str,
        value: Any,
        source: ParamSource | str,
        confidence: ConfidenceLevel | str = ConfidenceLevel.MEDIUM,
        source_step_index: Optional[int] = None,
        source_tool_name: Optional[str] = None,
        source_evidence_id: Optional[str] = None,
        user_confirmed: bool = False,
        increment_revision: bool = True,
    ) -> None:
        context.known_params[key] = value
        context.param_provenance[key] = ParamProvenance(
            key=key,
            source=source,
            confidence=confidence,
            source_step_index=source_step_index,
            source_tool_name=source_tool_name,
            source_evidence_id=source_evidence_id,
            user_confirmed=user_confirmed,
            revision_created=context.revision,
        )
        if increment_revision:
            DiagnosisContextManager.increment_revision(context)

    @staticmethod
    def apply_step_result(
        context: DiagnosisContext,
        tool_name: str,
        arguments: Dict[str, Any],
        result_summary: Dict[str, Any],
        evidence_id: Optional[str] = None,
        next_step: Optional[Dict[str, Any]] = None,
        argument_sources: Optional[Dict[str, str]] = None,
        produced_params: Optional[Dict[str, Any]] = None,
        depends_on_params: Optional[Iterable[str]] = None,
        step_id: Optional[str] = None,
        elapsed_ms: Optional[int] = None,
    ) -> StepRecord:
        step_index = len(context.completed_steps) + len(context.invalidated_steps) + 1
        record = StepRecord(
            step_id=step_id or f"dstep_{uuid.uuid4().hex}",
            step_index=step_index,
            tool_name=tool_name,
            arguments=dict(arguments or {}),
            argument_sources=dict(argument_sources or {}),
            result_summary=dict(result_summary or {}),
            evidence_id=evidence_id,
            next_step=next_step,
            produced_params=list((produced_params or {}).keys()),
            depends_on_params=list(depends_on_params or []),
            revision_created=context.revision,
            elapsed_ms=elapsed_ms,
        )
        context.completed_steps.append(record)
        context.current_step_index = step_index
        context.current_tool_name = tool_name
        if evidence_id and evidence_id not in context.effective_evidence_ids:
            context.effective_evidence_ids.append(evidence_id)
        for key, value in (produced_params or {}).items():
            DiagnosisContextManager.add_or_update_param(
                context,
                key=key,
                value=value,
                source=ParamSource.MCP_OUTPUT,
                confidence=ConfidenceLevel.HIGH,
                source_step_index=step_index,
                source_tool_name=tool_name,
                source_evidence_id=evidence_id,
                increment_revision=False,
            )
        DiagnosisContextManager.increment_revision(context)
        return record

    @staticmethod
    def add_candidate_set(context: DiagnosisContext, candidate_set: CandidateSet, primary: bool = True) -> None:
        if primary:
            for existing in context.candidate_sets:
                if (
                    existing.candidate_set_id == context.primary_candidate_set_id
                    and existing.status == CandidateSetStatus.ACTIVE
                ):
                    existing.status = CandidateSetStatus.SUPERSEDED
            context.primary_candidate_set_id = candidate_set.candidate_set_id
        candidate_set.created_revision = context.revision
        context.candidate_sets.append(candidate_set)
        DiagnosisContextManager.increment_revision(context)

    @staticmethod
    def invalidate_candidate_sets_from_step(context: DiagnosisContext, step_index: int, revision: Optional[int] = None) -> None:
        invalidated_revision = revision if revision is not None else context.revision
        for candidate_set in context.candidate_sets:
            if candidate_set.source_step_index is not None and candidate_set.source_step_index >= step_index:
                candidate_set.status = CandidateSetStatus.INVALIDATED
                candidate_set.invalidated_revision = invalidated_revision
                if context.primary_candidate_set_id == candidate_set.candidate_set_id:
                    context.primary_candidate_set_id = None

    @staticmethod
    def schema_hash(schema: Dict[str, Any]) -> str:
        canonical = json.dumps(schema or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
