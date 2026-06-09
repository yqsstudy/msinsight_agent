import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.core.diagnosis import DiagnosisContextManager, InvalidationEngine, ReportEvidenceValidator


def build_context():
    context = DiagnosisContextManager.create("ses_1", "goal")
    for index in range(1, 4):
        DiagnosisContextManager.apply_step_result(
            context,
            tool_name=f"tool_{index}",
            arguments={},
            result_summary={"summary": f"step {index}"},
            evidence_id=f"ev_{index}",
            produced_params={f"p{index}": index},
        )
    return context


def test_get_effective_evidence_excludes_invalidated_evidence():
    context = build_context()
    InvalidationEngine().invalidate_from_step(context, 2, "rollback")
    validator = ReportEvidenceValidator()

    assert validator.get_effective_evidence(context) == ["ev_1"]


def test_current_report_rejects_invalidated_and_unlinked_evidence():
    context = build_context()
    InvalidationEngine().invalidate_from_step(context, 2, "rollback")
    validator = ReportEvidenceValidator()

    result = validator.validate_current_report_evidence(context, ["ev_1", "ev_2", "ev_unknown"])

    assert result.valid is False
    assert result.effective_evidence_ids == ["ev_1"]
    assert result.rejected_evidence_ids == ["ev_2", "ev_unknown"]
    assert result.reasons["ev_2"] == "evidence_invalidated"
    assert result.reasons["ev_unknown"] == "evidence_not_effective"
    assert result.disclaimer is None


def test_current_report_accepts_only_effective_evidence():
    context = build_context()
    validator = ReportEvidenceValidator()

    result = validator.validate_current_report_evidence(context, ["ev_1", "ev_2"])

    assert result.valid is True
    assert result.effective_evidence_ids == ["ev_1", "ev_2"]
    assert result.rejected_evidence_ids == []


def test_historical_report_allows_invalidated_evidence_with_disclaimer():
    context = build_context()
    InvalidationEngine().invalidate_from_step(context, 2, "rollback")
    validator = ReportEvidenceValidator()

    result = validator.validate_historical_report_evidence(context, ["ev_2"])

    assert result.valid is True
    assert result.effective_evidence_ids == ["ev_2"]
    assert result.disclaimer == ReportEvidenceValidator.HISTORICAL_DISCLAIMER
