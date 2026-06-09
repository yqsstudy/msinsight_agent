import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.core.diagnosis import DiagnosisContextManager, DiagnosisStatus, PlaybookSwitchManager


def test_explicit_playbook_switch_supersedes_old_path_without_param_migration():
    context = DiagnosisContextManager.create("ses_1", "old goal", extracted={"path": "/tmp/old"})
    DiagnosisContextManager.apply_step_result(context, "tool_1", {"path": "/tmp/old"}, {}, evidence_id="ev_1", produced_params={"rank": 3})

    result, new_context = PlaybookSwitchManager().switch_playbook(context, "切换到通信剧本", selected_playbook="communication")

    assert result.action == "switch"
    assert result.old_diagnosis_id == context.diagnosis_id
    assert result.new_diagnosis_id == new_context.diagnosis_id
    assert result.migrated_params == {}
    assert context.status == DiagnosisStatus.SUPERSEDED
    assert context.effective_evidence_ids == []
    assert context.invalidated_evidence_ids == ["ev_1"]
    assert new_context.selected_playbook == "communication"
    assert new_context.known_params == {"selected_playbook": "communication"}
    assert "rank" not in new_context.known_params


def test_ambiguous_playbook_switch_requires_clarification():
    context = DiagnosisContextManager.create("ses_1", "goal")
    manager = PlaybookSwitchManager()

    assert manager.detect_switch_intent("换个剧本看看") == "ambiguous"
    result = manager.clarification(context)

    assert result.action == "clarify"
    assert result.old_diagnosis_id == context.diagnosis_id


def test_explicit_switch_intent_detected():
    assert PlaybookSwitchManager().detect_switch_intent("切换到通信剧本") == "explicit"
