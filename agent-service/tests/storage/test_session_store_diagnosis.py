import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.core.diagnosis import DiagnosisContextManager, DiagnosisOperation, OperationStatus, OperationType
from src.core.diagnosis.audit import DiagnosisAuditWriter
from src.storage.session_store import SessionStore


def test_diagnosis_context_crud_and_status_queries(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.db"))
    context = DiagnosisContextManager.create(
        session_id="ses_1",
        plan_id="plan_1",
        root_message="分析 /tmp/trace",
        extracted={"path": "/tmp/trace"},
    )

    store.create_diagnosis_context(context)
    loaded = store.get_diagnosis_context(context.diagnosis_id)

    assert loaded == context
    assert store.get_active_diagnosis_context("ses_1").diagnosis_id == context.diagnosis_id
    assert [item.diagnosis_id for item in store.list_diagnosis_contexts("ses_1")] == [context.diagnosis_id]
    assert [item.diagnosis_id for item in store.list_diagnosis_contexts("ses_1", status="active")] == [context.diagnosis_id]
    assert store.list_diagnosis_contexts("ses_1", status="paused") == []

    DiagnosisContextManager.mark_status(context, "paused")
    store.update_diagnosis_context(context)

    assert store.get_active_diagnosis_context("ses_1") is None
    assert store.list_diagnosis_contexts("ses_1", status="paused")[0].status == "paused"


def test_diagnosis_operation_crud_fifo_and_idempotency(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.db"))
    first = DiagnosisOperation(
        operation_id="op_1",
        idempotency_key="idem_1",
        session_id="ses_1",
        diagnosis_id="diag_1",
        type=OperationType.ANSWER_PENDING,
        payload={"answer": "rank 3"},
        target_pending_id="pin_1",
        expected_revision=2,
    )
    second = DiagnosisOperation(
        operation_id="op_2",
        session_id="ses_1",
        diagnosis_id="diag_1",
        type=OperationType.PAUSE,
        payload={"reason": "user"},
    )

    store.create_diagnosis_operation(first)
    store.create_diagnosis_operation(second)

    assert store.get_diagnosis_operation("op_1") == first
    assert store.find_operation_by_idempotency_key("ses_1", "idem_1").operation_id == "op_1"
    assert [item.operation_id for item in store.list_queued_operations("ses_1")] == ["op_1", "op_2"]

    first.status = OperationStatus.RUNNING
    first.started_at = datetime.utcnow()
    store.update_diagnosis_operation(first)

    assert store.get_diagnosis_operation("op_1").status == OperationStatus.RUNNING
    assert [item.operation_id for item in store.list_queued_operations("ses_1")] == ["op_2"]


def test_diagnosis_operation_unique_idempotency_key(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.db"))
    store.create_diagnosis_operation(DiagnosisOperation(
        operation_id="op_1",
        idempotency_key="idem_1",
        session_id="ses_1",
        type=OperationType.ANSWER_PENDING,
    ))
    duplicate = DiagnosisOperation(
        operation_id="op_2",
        idempotency_key="idem_1",
        session_id="ses_1",
        type=OperationType.PAUSE,
    )

    try:
        store.create_diagnosis_operation(duplicate)
    except Exception:
        pass

    existing = store.find_operation_by_idempotency_key("ses_1", "idem_1")
    assert existing.operation_id == "op_1"


def test_diagnosis_audit_event_persistence_and_filtering(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.db"))
    context = DiagnosisContextManager.create("ses_1", "goal")
    other = DiagnosisContextManager.create("ses_1", "other")
    writer = DiagnosisAuditWriter(store)

    event = writer.write("param_added", context, {"key": "path"})
    writer.write("step_started", other, {"tool": "x"})

    all_events = store.list_diagnosis_audit_events("ses_1")
    filtered = store.list_diagnosis_audit_events("ses_1", context.diagnosis_id)

    assert [item.event_type for item in all_events] == ["param_added", "step_started"]
    assert filtered == [event]
    assert filtered[0].payload == {"key": "path"}


def test_schema_initialization_is_idempotent_for_diagnosis_tables(tmp_path):
    db_path = str(tmp_path / "sessions.db")
    first = SessionStore(db_path)
    second = SessionStore(db_path)

    context = DiagnosisContextManager.create("ses_1", "goal")
    first.create_diagnosis_context(context)

    assert second.get_diagnosis_context(context.diagnosis_id) == context
