"""Compact DiagnosisContext views for LLM assistance and SSE summaries."""

from __future__ import annotations

from typing import Any, Dict, List

from .models import CandidateSetStatus, DiagnosisContext, ParamProvenance, StepRecord


def compact_for_llm(
    context: DiagnosisContext,
    stage: str | None = None,
    max_completed_steps: int = 3,
    max_candidates: int = 20,
) -> Dict[str, Any]:
    """Build a bounded, effective-only context for advisory LLM calls.

    Invalidated step details, raw MCP payloads, all historical messages, all paused
    contexts and obsolete schema arguments are intentionally excluded.
    """

    effective_steps = [step for step in context.completed_steps if step.status == "completed"]
    latest_steps = effective_steps[-max_completed_steps:]
    active_candidate_set = _active_candidate_set(context)

    compact: Dict[str, Any] = {
        "stage": stage,
        "diagnosis_id": context.diagnosis_id,
        "context_revision": context.revision,
        "user_goal": context.root_message,
        "latest_user_input": context.latest_user_input,
        "status": context.status,
        "selected_playbook": context.selected_playbook,
        "playbook_name": context.playbook_name,
        "current_step_index": context.current_step_index,
        "current_tool": context.current_tool_name,
        "known_params": dict(context.known_params),
        "param_sources": _compact_param_sources(context.param_provenance),
        "latest_completed_steps": [_compact_step(step) for step in latest_steps],
        "last_mcp_result_summary": _compact_step(effective_steps[-1])["result_summary"] if effective_steps else None,
        "active_candidate_set": _compact_candidate_set(active_candidate_set, max_candidates) if active_candidate_set else None,
        "pending": _compact_pending(context),
        "invalidated_summary": _compact_invalidated_summary(context),
        "effective_evidence_ids": list(context.effective_evidence_ids),
    }
    return compact


def compact_for_sse(context: DiagnosisContext, max_completed_steps: int = 5, max_candidates: int = 20) -> Dict[str, Any]:
    """Build a user-visible summary safe for frontend state updates."""

    active_candidate_set = _active_candidate_set(context)
    return {
        "diagnosis_id": context.diagnosis_id,
        "session_id": context.session_id,
        "plan_id": context.plan_id,
        "status": context.status,
        "revision": context.revision,
        "root_message": context.root_message,
        "selected_playbook": context.selected_playbook,
        "playbook_name": context.playbook_name,
        "current_step_index": context.current_step_index,
        "current_tool_name": context.current_tool_name,
        "known_params": dict(context.known_params),
        "param_sources": _compact_param_sources(context.param_provenance),
        "completed_steps": [_compact_step(step) for step in context.completed_steps[-max_completed_steps:]],
        "invalidated_step_count": len(context.invalidated_steps),
        "pending": _compact_pending(context),
        "active_candidate_set": _compact_candidate_set(active_candidate_set, max_candidates) if active_candidate_set else None,
        "effective_evidence_ids": list(context.effective_evidence_ids),
        "invalidated_evidence_ids": list(context.invalidated_evidence_ids),
        "operation_queue_snapshot": list(context.operation_queue_snapshot),
        "total_auto_steps": context.total_auto_steps,
    }


def _compact_param_sources(provenance: Dict[str, ParamProvenance]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for key, item in provenance.items():
        if item.invalidated:
            continue
        result[key] = {
            "source": item.source,
            "confidence": item.confidence,
            "source_step_index": item.source_step_index,
            "source_tool_name": item.source_tool_name,
            "source_evidence_id": item.source_evidence_id,
            "user_confirmed": item.user_confirmed,
            "revision_created": item.revision_created,
        }
    return result


def _compact_step(step: StepRecord) -> Dict[str, Any]:
    return {
        "step_id": step.step_id,
        "step_index": step.step_index,
        "tool_name": step.tool_name,
        "arguments": dict(step.arguments),
        "argument_sources": dict(step.argument_sources),
        "result_summary": dict(step.result_summary),
        "evidence_id": step.evidence_id,
        "next_tool_name": (step.next_step or {}).get("tool_name") if isinstance(step.next_step, dict) else None,
        "produced_params": list(step.produced_params),
        "depends_on_params": list(step.depends_on_params),
        "elapsed_ms": step.elapsed_ms,
    }


def _active_candidate_set(context: DiagnosisContext):
    if not context.primary_candidate_set_id:
        return None
    for candidate_set in context.candidate_sets:
        if (
            candidate_set.candidate_set_id == context.primary_candidate_set_id
            and candidate_set.status == CandidateSetStatus.ACTIVE
        ):
            return candidate_set
    return None


def _compact_candidate_set(candidate_set, max_candidates: int) -> Dict[str, Any]:
    return {
        "candidate_set_id": candidate_set.candidate_set_id,
        "type": candidate_set.type,
        "source_step_index": candidate_set.source_step_index,
        "source_tool_name": candidate_set.source_tool_name,
        "status": candidate_set.status,
        "candidate_count": len(candidate_set.candidates),
        "candidates": [
            {
                "global_index": item.global_index,
                "value": item.value,
                "label": item.label,
                "description": item.description,
                "metadata": item.metadata,
            }
            for item in candidate_set.candidates[:max_candidates]
        ],
        "truncated": len(candidate_set.candidates) > max_candidates,
    }


def _compact_pending(context: DiagnosisContext) -> Dict[str, Any] | None:
    if not context.pending:
        return None
    pending = context.pending
    return {
        "pending_id": pending.pending_id,
        "resume_action": pending.resume_action,
        "tool_name": pending.tool_name,
        "required_missing": list(pending.required_missing),
        "auto_step_count": pending.auto_step_count,
        "reason": pending.reason,
        "candidate_set_id": pending.candidate_set_id,
        "created_revision": pending.created_revision,
        "tool_schema_hash": pending.tool_schema_hash,
    }


def _compact_invalidated_summary(context: DiagnosisContext) -> List[Dict[str, Any]]:
    return [
        {
            "step_index": step.step_index,
            "tool_name": step.tool_name,
            "revision_invalidated": step.revision_invalidated,
            "reason": step.invalidation_reason,
        }
        for step in context.invalidated_steps[-5:]
    ]
