import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.core.diagnosis import DiagnosisContextManager, DiagnosisOperationQueue, OperationStatus, OperationType
from src.core.diagnosis.models import PendingStepState
from src.storage.session_store import SessionStore


def setup_store(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.db"))
    context = DiagnosisContextManager.create("ses_1", "goal", diagnosis_id="diag_1")
    DiagnosisContextManager.set_pending(context, PendingStepState(
        pending_id="pin_1",
        resume_action="continue_mcp_with_args",
        required_missing=["rank"],
    ))
    store.create_diagnosis_context(context)
    return store, context


def test_enqueue_or_get_existing_uses_idempotency_key(tmp_path):
    store, context = setup_store(tmp_path)
    queue = DiagnosisOperationQueue(store)

    first = queue.enqueue_or_get_existing("ses_1", OperationType.ANSWER_PENDING, {"answer": "rank 3"}, diagnosis_id=context.diagnosis_id, idempotency_key="idem_1")
    second = queue.enqueue_or_get_existing("ses_1", OperationType.ANSWER_PENDING, {"answer": "rank 3"}, diagnosis_id=context.diagnosis_id, idempotency_key="idem_1")

    assert first.operation_id == second.operation_id
    assert queue.queue_length("ses_1") == 1


def test_enqueue_weak_dedupe_for_missing_frontend_key(tmp_path):
    store, context = setup_store(tmp_path)
    queue = DiagnosisOperationQueue(store)

    first = queue.enqueue_or_get_existing("ses_1", OperationType.ANSWER_PENDING, {"answer": "rank 3"}, diagnosis_id=context.diagnosis_id, target_pending_id="pin_1")
    second = queue.enqueue_or_get_existing("ses_1", OperationType.ANSWER_PENDING, {"answer": "rank 3"}, diagnosis_id=context.diagnosis_id, target_pending_id="pin_1")

    assert first.operation_id == second.operation_id


def test_process_next_runs_fifo_and_blocks_when_running(tmp_path):
    store, context = setup_store(tmp_path)
    queue = DiagnosisOperationQueue(store)
    first = queue.enqueue_or_get_existing("ses_1", OperationType.ANSWER_PENDING, {"answer": 1}, diagnosis_id=context.diagnosis_id, idempotency_key="1")
    second = queue.enqueue_or_get_existing("ses_1", OperationType.PAUSE, {}, diagnosis_id=context.diagnosis_id, idempotency_key="2")

    running = queue.process_next("ses_1")
    still_running = queue.process_next("ses_1")

    assert running.operation_id == first.operation_id
    assert running.status == OperationStatus.RUNNING
    assert still_running.operation_id == first.operation_id
    assert [item.operation_id for item in store.list_queued_operations("ses_1")] == [second.operation_id]

    queue.complete(running)
    next_running = queue.process_next("ses_1")

    assert next_running.operation_id == second.operation_id


def test_process_next_marks_stale_when_revision_mismatches(tmp_path):
    store, context = setup_store(tmp_path)
    queue = DiagnosisOperationQueue(store)
    stale = queue.enqueue_or_get_existing(
        "ses_1",
        OperationType.ANSWER_PENDING,
        {"answer": "rank 3"},
        diagnosis_id=context.diagnosis_id,
        target_pending_id="pin_1",
        expected_revision=context.revision + 100,
        idempotency_key="stale",
    )
    valid = queue.enqueue_or_get_existing(
        "ses_1",
        OperationType.PAUSE,
        {},
        diagnosis_id=context.diagnosis_id,
        expected_revision=context.revision,
        idempotency_key="valid",
    )

    running = queue.process_next("ses_1")

    assert store.get_diagnosis_operation(stale.operation_id).status == OperationStatus.STALE
    assert running.operation_id == valid.operation_id
    assert running.status == OperationStatus.RUNNING


def test_process_next_marks_stale_when_pending_target_changed(tmp_path):
    store, context = setup_store(tmp_path)
    queue = DiagnosisOperationQueue(store)
    stale = queue.enqueue_or_get_existing(
        "ses_1",
        OperationType.ANSWER_PENDING,
        {"answer": "rank 3"},
        diagnosis_id=context.diagnosis_id,
        target_pending_id="pin_old",
        expected_revision=context.revision,
        idempotency_key="stale_pending",
    )

    assert queue.process_next("ses_1") is None
    assert store.get_diagnosis_operation(stale.operation_id).status == OperationStatus.STALE


def test_complete_writes_operation_audit_event(tmp_path):
    store, context = setup_store(tmp_path)
    queue = DiagnosisOperationQueue(store)
    operation = queue.enqueue_or_get_existing("ses_1", OperationType.PAUSE, {}, diagnosis_id=context.diagnosis_id, idempotency_key="pause")
    running = queue.process_next("ses_1")

    queue.complete(running)
    events = store.list_diagnosis_audit_events("ses_1", context.diagnosis_id)

    assert [event.event_type for event in events] == ["operation_queued", "operation_running", "operation_completed"]
    assert store.get_diagnosis_operation(operation.operation_id).status == OperationStatus.COMPLETED
