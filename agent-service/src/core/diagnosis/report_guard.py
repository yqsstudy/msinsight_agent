"""Evidence validity guard for diagnosis reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from ...observability.metrics import record_diagnosis_report
from .models import DiagnosisContext, StepStatus


@dataclass(frozen=True)
class ReportEvidenceValidationResult:
    valid: bool
    effective_evidence_ids: List[str]
    rejected_evidence_ids: List[str]
    reasons: dict[str, str]
    disclaimer: str | None = None


class ReportEvidenceValidator:
    """Ensure current reports only use effective diagnosis evidence."""

    HISTORICAL_DISCLAIMER = "该报告基于历史/已失效 evidence 生成，不代表当前诊断上下文的有效结论。"

    def get_effective_evidence(self, context: DiagnosisContext) -> List[str]:
        completed_evidence = {
            step.evidence_id
            for step in context.completed_steps
            if step.status == StepStatus.COMPLETED and step.evidence_id
        }
        return [
            evidence_id
            for evidence_id in context.effective_evidence_ids
            if evidence_id in completed_evidence and evidence_id not in context.invalidated_evidence_ids
        ]

    def validate_current_report_evidence(
        self,
        context: DiagnosisContext,
        evidence_ids: Iterable[str],
    ) -> ReportEvidenceValidationResult:
        effective = set(self.get_effective_evidence(context))
        requested = list(evidence_ids)
        accepted = [evidence_id for evidence_id in requested if evidence_id in effective]
        rejected = [evidence_id for evidence_id in requested if evidence_id not in effective]
        reasons = {evidence_id: self._reject_reason(context, evidence_id) for evidence_id in rejected}
        excluded_invalidated = sum(1 for evidence_id in rejected if evidence_id in context.invalidated_evidence_ids)
        record_diagnosis_report("current", excluded_invalidated_evidence=excluded_invalidated)
        return ReportEvidenceValidationResult(
            valid=not rejected,
            effective_evidence_ids=accepted,
            rejected_evidence_ids=rejected,
            reasons=reasons,
        )

    def validate_historical_report_evidence(
        self,
        context: DiagnosisContext,
        evidence_ids: Iterable[str],
    ) -> ReportEvidenceValidationResult:
        requested = list(evidence_ids)
        known = set(context.effective_evidence_ids) | set(context.invalidated_evidence_ids)
        accepted = [evidence_id for evidence_id in requested if evidence_id in known]
        rejected = [evidence_id for evidence_id in requested if evidence_id not in known]
        record_diagnosis_report("historical")
        return ReportEvidenceValidationResult(
            valid=not rejected,
            effective_evidence_ids=accepted,
            rejected_evidence_ids=rejected,
            reasons={evidence_id: "evidence_not_in_diagnosis_context" for evidence_id in rejected},
            disclaimer=self.HISTORICAL_DISCLAIMER,
        )

    def _reject_reason(self, context: DiagnosisContext, evidence_id: str) -> str:
        if evidence_id in context.invalidated_evidence_ids:
            return "evidence_invalidated"
        if evidence_id not in context.effective_evidence_ids:
            return "evidence_not_effective"
        for step in context.invalidated_steps:
            if step.evidence_id == evidence_id:
                return "source_step_invalidated"
        for step in context.completed_steps:
            if step.evidence_id == evidence_id and step.status != StepStatus.COMPLETED:
                return "source_step_not_completed"
        return "evidence_not_linked_to_completed_step"
