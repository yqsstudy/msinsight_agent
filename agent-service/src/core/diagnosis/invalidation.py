"""Diagnosis rollback and downstream invalidation."""

from __future__ import annotations

from typing import List

from ...observability.metrics import record_diagnosis_rollback
from .context import DiagnosisContextManager
from .models import CandidateSetStatus, DiagnosisContext, StepRecord, StepStatus


class InvalidationEngine:
    """Apply linear downstream invalidation for historical step changes.

    P6 intentionally implements the confirmed linear truncation semantics: Step N
    and all following completed steps become invalidated. Future DAG-level
    invalidation can replace the selection strategy without changing the public
    method contract.
    """

    def invalidate_from_step(self, context: DiagnosisContext, step_index: int, reason: str) -> List[StepRecord]:
        if step_index < 1:
            raise ValueError("step_index must be >= 1")

        affected = [step for step in context.completed_steps if step.step_index >= step_index]
        if not affected:
            return []

        revision = DiagnosisContextManager.increment_revision(context)
        remaining = [step for step in context.completed_steps if step.step_index < step_index]
        invalidated_records: list[StepRecord] = []

        for step in affected:
            step.status = StepStatus.INVALIDATED
            step.revision_invalidated = revision
            step.invalidation_reason = reason
            invalidated_records.append(step)
            if step.evidence_id:
                if step.evidence_id in context.effective_evidence_ids:
                    context.effective_evidence_ids.remove(step.evidence_id)
                if step.evidence_id not in context.invalidated_evidence_ids:
                    context.invalidated_evidence_ids.append(step.evidence_id)
            for key in step.produced_params:
                provenance = context.param_provenance.get(key)
                if provenance:
                    provenance.invalidated = True
                    provenance.revision_invalidated = revision
                if key in context.known_params:
                    del context.known_params[key]

        context.completed_steps = remaining
        context.invalidated_steps.extend(invalidated_records)
        self._invalidate_candidate_sets(context, step_index, revision)
        if context.pending and context.current_step_index is not None and context.current_step_index >= step_index:
            context.pending = None
        context.current_step_index = remaining[-1].step_index if remaining else None
        context.current_tool_name = remaining[-1].tool_name if remaining else None
        record_diagnosis_rollback(reason, len(invalidated_records))
        return invalidated_records

    def _invalidate_candidate_sets(self, context: DiagnosisContext, step_index: int, revision: int) -> None:
        for candidate_set in context.candidate_sets:
            if candidate_set.source_step_index is not None and candidate_set.source_step_index >= step_index:
                candidate_set.status = CandidateSetStatus.INVALIDATED
                candidate_set.invalidated_revision = revision
                if context.primary_candidate_set_id == candidate_set.candidate_set_id:
                    context.primary_candidate_set_id = None
