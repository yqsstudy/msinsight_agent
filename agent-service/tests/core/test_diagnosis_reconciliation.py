import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.core.diagnosis import DiagnosisContextManager, ReconciliationEngine
from src.core.diagnosis.models import ReconciliationStatus


def context_with_steps():
    context = DiagnosisContextManager.create("ses_1", "goal")
    DiagnosisContextManager.apply_step_result(context, "import_trace", {}, {}, evidence_id="ev_1")
    DiagnosisContextManager.apply_step_result(context, "analyze_rank", {"rank": 3}, {}, evidence_id="ev_2")
    return context


def test_blocked_required_step_returns_execute_required_step():
    context = context_with_steps()
    result = ReconciliationEngine().reconcile(
        context,
        {"status": "blocked", "required_step": {"tool_name": "import_trace", "arguments": {"file_path": "/tmp/a"}}},
        "analyze_rank",
        {"rank": 3},
    )

    assert result.action == "execute_required_step"
    assert result.required_tool == "import_trace"
    assert result.required_arguments == {"file_path": "/tmp/a"}
    assert result.invalidated_from_step == 1
    assert context.invalidated_steps[0].tool_name == "import_trace"


def test_same_blocked_reason_is_limited_to_one_auto_fix():
    context = context_with_steps()
    engine = ReconciliationEngine()
    payload = {"status": "blocked", "reason": "blocked: missing import", "required_step": {"tool_name": "import_trace"}}

    first = engine.reconcile(context, payload, "analyze_rank", {})
    second = engine.reconcile(context, payload, "analyze_rank", {})

    assert first.action == "execute_required_step"
    assert second.action == "suspend"
    assert second.exceeded_limit is True
    assert context.reconciliation_state.status == ReconciliationStatus.SUSPENDED


def test_stale_current_tool_invalidates_from_current_step_and_retries():
    context = context_with_steps()

    result = ReconciliationEngine().reconcile(context, {"status": "stale context_changed"}, "analyze_rank", {"rank": 3})

    assert result.action == "retry_current_step"
    assert result.required_tool == "analyze_rank"
    assert result.invalidated_from_step == 2
    assert context.completed_steps[0].tool_name == "import_trace"
    assert context.invalidated_steps[0].tool_name == "analyze_rank"


def test_non_reconciliation_result_returns_none_action():
    context = context_with_steps()

    result = ReconciliationEngine().reconcile(context, {"status": "completed"}, "analyze_rank", {})

    assert result.action == "none"
