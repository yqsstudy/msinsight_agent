"""Audit event helpers for diagnosis context state changes."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from .models import DiagnosisAuditEvent, DiagnosisContext


class DiagnosisAuditWriter:
    """Small adapter around SessionStore diagnosis audit persistence.

    P1 keeps this intentionally thin: if a store does not yet expose the P2
    persistence method, callers still receive the event object and can decide how
    to handle it. P2 will make persistence mandatory through SessionStore.
    """

    def __init__(self, session_store: Any | None = None):
        self.session_store = session_store

    def write(
        self,
        event_type: str,
        context: DiagnosisContext,
        payload: Optional[Dict[str, Any]] = None,
    ) -> DiagnosisAuditEvent:
        event = DiagnosisAuditEvent(
            id=f"daud_{uuid.uuid4().hex}",
            session_id=context.session_id,
            diagnosis_id=context.diagnosis_id,
            event_type=event_type,
            revision=context.revision,
            payload=payload or {},
        )
        if self.session_store and hasattr(self.session_store, "create_diagnosis_audit_event"):
            self.session_store.create_diagnosis_audit_event(event)
        return event
