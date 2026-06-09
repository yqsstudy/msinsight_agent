import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.observability import metrics


def test_diagnosis_metric_helpers_accept_expected_labels():
    metrics.record_diagnosis_user_prompt("missing_required_arguments")
    metrics.record_diagnosis_auto_fill(True, "known_param")
    metrics.record_diagnosis_auto_fill(False, "missing")
    metrics.record_diagnosis_param_conflict("requires_confirmation")
    metrics.record_diagnosis_rollback("rollback", 2)
    metrics.record_diagnosis_reconciliation("retry_current_step")
    metrics.record_diagnosis_reconciliation("suspend", failed_reason="blocked")
    metrics.record_diagnosis_operation_queued("answer_pending", queue_length=1, session_id="ses_1")
    metrics.record_diagnosis_operation_stale("answer_pending")
    metrics.record_diagnosis_operation_wait("answer_pending", 0.1)
    metrics.record_diagnosis_candidate_set("created", "rank")
    metrics.record_diagnosis_candidate_set("selected", "rank")
    metrics.record_diagnosis_candidate_set("invalidated", "rank")
    metrics.record_diagnosis_schema_migration("tool", drift_detected=True, success=True)
    metrics.record_diagnosis_schema_migration("tool", drift_detected=True, success=False)
    metrics.record_diagnosis_auto_step("tool")
    metrics.record_diagnosis_auto_limit("turn")
    metrics.record_diagnosis_report("current", excluded_invalidated_evidence=1)

    assert metrics.DIAGNOSIS_OPERATION_QUEUE_LENGTH.labels(session_id="ses_1")._value.get() == 1
