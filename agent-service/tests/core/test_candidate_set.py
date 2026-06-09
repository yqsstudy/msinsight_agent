import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.core.diagnosis import CandidateSetManager, CandidateSetStatus, CandidateSetType, DiagnosisContextManager
from src.core.diagnosis.compact import compact_for_llm


def test_create_candidate_set_assigns_global_stable_indices():
    context = DiagnosisContextManager.create("ses_1", "goal")
    manager = CandidateSetManager()

    first = manager.create_candidate_set(context, CandidateSetType.PLAYBOOK, [{"id": "a"}, {"id": "b"}], source_step_index=1)
    second = manager.create_candidate_set(context, CandidateSetType.RANK, [3, 4], source_step_index=2)

    assert [item.global_index for item in first.candidates] == [1, 2]
    assert [item.global_index for item in second.candidates] == [3, 4]
    assert first.status == CandidateSetStatus.SUPERSEDED
    assert second.status == CandidateSetStatus.ACTIVE
    assert context.primary_candidate_set_id == second.candidate_set_id


def test_resolve_selection_binds_ordinal_to_active_candidate_set():
    context = DiagnosisContextManager.create("ses_1", "goal")
    manager = CandidateSetManager()
    manager.create_candidate_set(context, CandidateSetType.RANK, ["rank0", "rank1", "rank2"], source_step_index=1)

    selected = manager.resolve_selection("第二个", context)

    assert selected.value == "rank1"
    assert selected.global_index == 2


def test_select_candidate_marks_selected_and_records_param():
    context = DiagnosisContextManager.create("ses_1", "goal")
    manager = CandidateSetManager()
    cset = manager.create_candidate_set(context, CandidateSetType.OPERATOR, [{"id": "op_a", "name": "Operator A"}], source_step_index=2, source_tool_name="list_ops", source_evidence_id="ev_2")

    selected = manager.select_candidate(context, cset.candidate_set_id, 1, param_key="operator")

    assert selected.value == "op_a"
    assert cset.status == CandidateSetStatus.SELECTED
    assert context.primary_candidate_set_id is None
    assert context.known_params["operator"] == "op_a"
    assert context.param_provenance["operator"].source_step_index == 2
    assert context.param_provenance["operator"].user_confirmed is True


def test_source_step_invalidation_disables_selection():
    context = DiagnosisContextManager.create("ses_1", "goal")
    manager = CandidateSetManager()
    cset = manager.create_candidate_set(context, CandidateSetType.RANK, [1, 2], source_step_index=3)

    invalidated = manager.invalidate_by_source_step(context, 2)

    assert [item.candidate_set_id for item in invalidated] == [cset.candidate_set_id]
    assert cset.status == CandidateSetStatus.INVALIDATED
    assert context.primary_candidate_set_id is None
    with pytest.raises(ValueError):
        manager.resolve_selection("第二个", context, cset.candidate_set_id)


def test_superseded_candidate_set_cannot_resolve_after_primary_changes():
    context = DiagnosisContextManager.create("ses_1", "goal")
    manager = CandidateSetManager()
    first = manager.create_candidate_set(context, CandidateSetType.PLAYBOOK, ["a", "b"], source_step_index=1)
    second = manager.create_candidate_set(context, CandidateSetType.RANK, [3, 4], source_step_index=2)

    with pytest.raises(ValueError):
        manager.resolve_selection(2, context, first.candidate_set_id)

    assert first.status == CandidateSetStatus.SUPERSEDED
    assert second.status == CandidateSetStatus.ACTIVE


def test_compact_context_limits_active_candidates_to_twenty():
    context = DiagnosisContextManager.create("ses_1", "goal")
    manager = CandidateSetManager()
    manager.create_candidate_set(context, CandidateSetType.RANK, list(range(25)), source_step_index=1)

    compact = compact_for_llm(context)

    assert compact["active_candidate_set"]["candidate_count"] == 25
    assert len(compact["active_candidate_set"]["candidates"]) == 20
    assert compact["active_candidate_set"]["truncated"] is True
