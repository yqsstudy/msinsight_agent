import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.core.diagnosis import DiagnosisContextManager, DiagnosisTimelineBuilder
from src.core.diagnosis.audit import DiagnosisAuditWriter


def test_timeline_builder_projects_audit_events_in_time_order():
    context = DiagnosisContextManager.create("ses_1", "goal")
    writer = DiagnosisAuditWriter()
    later = writer.write("step_completed", context, {"tool_name": "tool_b"})
    earlier = writer.write("param_added", context, {"key": "path"})
    earlier.created_at = later.created_at.replace(year=later.created_at.year - 1)

    items = DiagnosisTimelineBuilder().build([later, earlier])

    assert [item.event_type for item in items] == ["param_added", "step_completed"]
    assert items[0].title == "参数新增"
    assert items[0].detail == "path"
    assert items[1].detail == "tool_b"
