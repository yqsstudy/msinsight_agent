import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.core.diagnosis import DiagnosisContextManager, SchemaDriftMigrator
from src.core.diagnosis.models import PendingStepState


def test_schema_drift_migrates_compatible_args_and_keeps_obsolete_for_audit():
    old_schema = {"properties": {"rank": {}, "old": {}}, "required": ["rank"]}
    new_schema = {"properties": {"rank": {}, "iteration": {}}, "required": ["rank", "iteration"]}
    context = DiagnosisContextManager.create("ses_1", "goal")
    pending = PendingStepState(
        pending_id="pin_1",
        resume_action="continue_mcp_with_args",
        tool_name="tool",
        tool_schema=old_schema,
        tool_schema_hash=DiagnosisContextManager.schema_hash(old_schema),
        resolved_arguments={"rank": 3, "old": "drop"},
    )
    DiagnosisContextManager.set_pending(context, pending)

    result = SchemaDriftMigrator().migrate_pending(context, pending, new_schema)

    assert result.drift_detected is True
    assert result.migrated_args == {"rank": 3}
    assert result.obsolete_args == {"old": "drop"}
    assert result.missing_required == ["iteration"]
    assert pending.resolved_arguments == {"rank": 3}
    assert pending.required_missing == ["iteration"]
    assert pending.tool_schema_hash == DiagnosisContextManager.schema_hash(new_schema)
    assert result.audit_payload["obsolete_args"] == {"old": "drop"}


def test_schema_drift_noop_when_schema_hash_same():
    schema = {"properties": {"rank": {}}, "required": ["rank"]}
    context = DiagnosisContextManager.create("ses_1", "goal")
    pending = PendingStepState(
        pending_id="pin_1",
        resume_action="continue_mcp_with_args",
        tool_name="tool",
        tool_schema=schema,
        tool_schema_hash=DiagnosisContextManager.schema_hash(schema),
        resolved_arguments={"rank": 3},
    )

    result = SchemaDriftMigrator().migrate_pending(context, pending, schema)

    assert result.drift_detected is False
    assert result.migrated_args == {"rank": 3}
    assert result.obsolete_args == {}
    assert result.missing_required == []
