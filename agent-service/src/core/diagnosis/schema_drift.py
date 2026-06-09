"""Schema drift migration for suspended diagnosis steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ...observability.metrics import record_diagnosis_schema_migration
from .context import DiagnosisContextManager
from .models import DiagnosisContext, PendingStepState


@dataclass(frozen=True)
class SchemaDriftMigrationResult:
    drift_detected: bool
    migrated_args: Dict[str, Any]
    obsolete_args: Dict[str, Any]
    missing_required: List[str]
    latest_schema_hash: str
    audit_payload: Dict[str, Any] = field(default_factory=dict)


class SchemaDriftMigrator:
    """Migrate pending resolved args to the latest tool schema."""

    def migrate_pending(
        self,
        context: DiagnosisContext,
        pending: PendingStepState,
        latest_schema: Dict[str, Any],
    ) -> SchemaDriftMigrationResult:
        latest_hash = DiagnosisContextManager.schema_hash(latest_schema)
        drift_detected = bool(pending.tool_schema_hash and pending.tool_schema_hash != latest_hash)
        properties = latest_schema.get("properties", {}) if isinstance(latest_schema, dict) else {}
        allowed = set(properties.keys()) if isinstance(properties, dict) else set()
        required = latest_schema.get("required", []) if isinstance(latest_schema, dict) else []
        required = [str(item) for item in required] if isinstance(required, list) else []

        migrated = {key: value for key, value in pending.resolved_arguments.items() if key in allowed and value not in (None, "")}
        obsolete = {key: value for key, value in pending.resolved_arguments.items() if key not in allowed}
        missing = [key for key in required if migrated.get(key) in (None, "")]

        pending.tool_schema = latest_schema
        pending.tool_schema_hash = latest_hash
        pending.resolved_arguments = migrated
        pending.required_missing = missing
        DiagnosisContextManager.increment_revision(context)

        record_diagnosis_schema_migration(pending.tool_name or "unknown", drift_detected, not missing)
        return SchemaDriftMigrationResult(
            drift_detected=drift_detected,
            migrated_args=migrated,
            obsolete_args=obsolete,
            missing_required=missing,
            latest_schema_hash=latest_hash,
            audit_payload={
                "diagnosis_id": context.diagnosis_id,
                "pending_id": pending.pending_id,
                "tool_name": pending.tool_name,
                "drift_detected": drift_detected,
                "obsolete_args": obsolete,
                "missing_required": missing,
            },
        )
