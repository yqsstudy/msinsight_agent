"""Session-level diagnosis mutation queue."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from ...observability.metrics import (
    record_diagnosis_operation_queued,
    record_diagnosis_operation_stale,
    record_diagnosis_operation_wait,
)
from .audit import DiagnosisAuditWriter
from .models import DiagnosisContext, DiagnosisOperation, OperationStatus, OperationType


class DiagnosisOperationQueue:
    """Persisted FIFO queue for diagnosis context mutations.

    The queue is storage-backed so process restarts can recover queued work. It
    serializes mutations per session by only allowing one running operation at a
    time and by validating each queued operation against the latest context before
    it runs.
    """

    def __init__(self, session_store: Any, audit_writer: Optional[DiagnosisAuditWriter] = None):
        self.session_store = session_store
        self.audit_writer = audit_writer or DiagnosisAuditWriter(session_store)

    def enqueue_or_get_existing(
        self,
        session_id: str,
        operation_type: OperationType | str,
        payload: Optional[Dict[str, Any]] = None,
        diagnosis_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        target_pending_id: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> DiagnosisOperation:
        if idempotency_key:
            existing = self.session_store.find_operation_by_idempotency_key(session_id, idempotency_key)
            if existing:
                return existing
        else:
            idempotency_key = self._weak_idempotency_key(session_id, target_pending_id, payload or {})
            existing = self.session_store.find_operation_by_idempotency_key(session_id, idempotency_key)
            if existing:
                return existing

        operation = DiagnosisOperation(
            operation_id=f"dop_{uuid.uuid4().hex}",
            session_id=session_id,
            diagnosis_id=diagnosis_id,
            idempotency_key=idempotency_key,
            type=operation_type,
            payload=payload or {},
            target_pending_id=target_pending_id,
            expected_revision=expected_revision,
        )
        stored = self.session_store.create_diagnosis_operation(operation)
        record_diagnosis_operation_queued(str(stored.type), self.queue_length(session_id), session_id)
        context = self._context_for_operation(stored)
        if context:
            self.audit_writer.write("operation_queued", context, {"operation_id": stored.operation_id, "type": stored.type})
        return stored

    def process_next(self, session_id: str) -> Optional[DiagnosisOperation]:
        running = self._running_operation(session_id)
        if running:
            return running
        queued = self.session_store.list_queued_operations(session_id)
        if not queued:
            return None
        operation = queued[0]
        context = self._context_for_operation(operation)
        if context and not self.validate_operation_against_latest_context(operation, context):
            operation.status = OperationStatus.STALE
            operation.completed_at = datetime.utcnow()
            self.session_store.update_diagnosis_operation(operation)
            record_diagnosis_operation_stale(str(operation.type))
            self.audit_writer.write("operation_stale", context, {"operation_id": operation.operation_id, "expected_revision": operation.expected_revision, "actual_revision": context.revision})
            return self.process_next(session_id)
        operation.status = OperationStatus.RUNNING
        operation.started_at = datetime.utcnow()
        record_diagnosis_operation_wait(str(operation.type), (operation.started_at - operation.created_at).total_seconds())
        self.session_store.update_diagnosis_operation(operation)
        if context:
            self.audit_writer.write("operation_running", context, {"operation_id": operation.operation_id, "type": operation.type})
        return operation

    def complete(self, operation: DiagnosisOperation, status: OperationStatus | str = OperationStatus.COMPLETED, error: Optional[str] = None) -> DiagnosisOperation:
        operation.status = status
        operation.completed_at = datetime.utcnow()
        operation.error = error
        self.session_store.update_diagnosis_operation(operation)
        context = self._context_for_operation(operation)
        if context:
            event_type = "operation_completed" if status == OperationStatus.COMPLETED else "operation_stale" if status == OperationStatus.STALE else "operation_failed"
            self.audit_writer.write(event_type, context, {"operation_id": operation.operation_id, "status": status, "error": error})
        return operation

    def validate_operation_against_latest_context(self, operation: DiagnosisOperation, context: DiagnosisContext) -> bool:
        if operation.diagnosis_id and operation.diagnosis_id != context.diagnosis_id:
            return False
        if operation.expected_revision is not None and operation.expected_revision != context.revision:
            return False
        if operation.target_pending_id and context.pending and context.pending.pending_id != operation.target_pending_id:
            return False
        if operation.target_pending_id and not context.pending and operation.type == OperationType.ANSWER_PENDING:
            return False
        return True

    def queue_length(self, session_id: str) -> int:
        return len(self.session_store.list_queued_operations(session_id))

    def _context_for_operation(self, operation: DiagnosisOperation) -> Optional[DiagnosisContext]:
        if operation.diagnosis_id:
            return self.session_store.get_diagnosis_context(operation.diagnosis_id)
        return self.session_store.get_active_diagnosis_context(operation.session_id)

    def _running_operation(self, session_id: str) -> Optional[DiagnosisOperation]:
        operations = getattr(self.session_store, "list_diagnosis_operations", None)
        if operations:
            for operation in operations(session_id, status=OperationStatus.RUNNING):
                return operation
        return None

    def _weak_idempotency_key(self, session_id: str, target_pending_id: Optional[str], payload: Dict[str, Any]) -> str:
        normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        bucket = int(datetime.utcnow().timestamp() // 30)
        raw = f"{session_id}:{target_pending_id or ''}:{normalized}:{bucket}"
        return "weak_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
