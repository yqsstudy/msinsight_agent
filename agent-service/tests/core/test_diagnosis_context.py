import json
import os
import sys

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.core.diagnosis import (
    CandidateItem,
    CandidateSet,
    CandidateSetStatus,
    CandidateSetType,
    ConfidenceLevel,
    DiagnosisContextManager,
    DiagnosisStatus,
    ParamSource,
    PendingStepState,
    compact_for_llm,
    compact_for_sse,
)


def test_create_context_serializes_extracted_params_with_provenance():
    context = DiagnosisContextManager.create(
        session_id="ses_1",
        plan_id="plan_1",
        root_message="分析 /tmp/trace 是否有快慢卡",
        extracted={"path": "/tmp/trace", "empty": ""},
    )

    assert context.diagnosis_id.startswith("diag_")
    assert context.session_id == "ses_1"
    assert context.plan_id == "plan_1"
    assert context.status == DiagnosisStatus.ACTIVE
    assert context.known_params == {"path": "/tmp/trace"}
    assert context.param_provenance["path"].source == ParamSource.BLACKBOARD_EXTRACTED
    assert context.param_provenance["path"].confidence == ConfidenceLevel.HIGH

    restored = DiagnosisContextManager.from_json(DiagnosisContextManager.to_json(context))

    assert restored == context


def test_add_or_update_param_increments_revision_and_replaces_provenance():
    context = DiagnosisContextManager.create("ses_1", "goal")
    initial_revision = context.revision

    DiagnosisContextManager.add_or_update_param(
        context,
        key="rank",
        value=3,
        source=ParamSource.USER_RESUME,
        confidence=ConfidenceLevel.HIGH,
        user_confirmed=True,
    )

    assert context.revision == initial_revision + 1
    assert context.known_params["rank"] == 3
    assert context.param_provenance["rank"].source == ParamSource.USER_RESUME
    assert context.param_provenance["rank"].user_confirmed is True


def test_apply_step_result_records_step_evidence_and_produced_params():
    context = DiagnosisContextManager.create("ses_1", "goal")

    record = DiagnosisContextManager.apply_step_result(
        context,
        tool_name="communication_duration_iterations",
        arguments={"file_path": "/tmp/trace"},
        argument_sources={"file_path": "path"},
        result_summary={"summary": "found slow rank", "raw": "kept only because caller summarized"},
        evidence_id="ev_1",
        next_step={"tool_name": "rank_detail", "schema": {"properties": {"rank": {"type": "integer"}}}},
        produced_params={"rank": 7, "iteration": 10},
        depends_on_params=["file_path"],
        elapsed_ms=123,
    )

    assert record.step_index == 1
    assert context.current_tool_name == "communication_duration_iterations"
    assert context.current_step_index == 1
    assert context.effective_evidence_ids == ["ev_1"]
    assert context.known_params["rank"] == 7
    assert context.known_params["iteration"] == 10
    assert context.param_provenance["rank"].source == ParamSource.MCP_OUTPUT
    assert context.param_provenance["rank"].source_step_index == 1
    assert context.param_provenance["rank"].source_evidence_id == "ev_1"
    assert context.completed_steps[0].elapsed_ms == 123


def test_pending_set_and_clear_updates_revision():
    context = DiagnosisContextManager.create("ses_1", "goal")
    pending = PendingStepState(
        pending_id="pin_1",
        resume_action="continue_mcp_with_args",
        tool_name="tool_a",
        required_missing=["rank"],
        reason="missing rank",
    )

    DiagnosisContextManager.set_pending(context, pending)
    revision_after_set = context.revision

    assert context.pending is not None
    assert context.pending.pending_id == "pin_1"
    assert context.pending.created_revision == 0

    assert DiagnosisContextManager.clear_pending(context, "wrong") is False
    assert context.revision == revision_after_set

    assert DiagnosisContextManager.clear_pending(context, "pin_1") is True
    assert context.pending is None
    assert context.revision == revision_after_set + 1


def test_candidate_set_primary_supersedes_existing_and_validates_indices():
    context = DiagnosisContextManager.create("ses_1", "goal")
    first = CandidateSet(
        candidate_set_id="cset_1",
        type=CandidateSetType.PLAYBOOK,
        candidates=[CandidateItem(global_index=1, value="a", label="A")],
    )
    second = CandidateSet(
        candidate_set_id="cset_2",
        type=CandidateSetType.RANK,
        candidates=[CandidateItem(global_index=2, value=2, label="Rank 2")],
    )

    DiagnosisContextManager.add_candidate_set(context, first, primary=True)
    DiagnosisContextManager.add_candidate_set(context, second, primary=True)

    assert context.primary_candidate_set_id == "cset_2"
    assert context.candidate_sets[0].status == CandidateSetStatus.SUPERSEDED
    assert context.candidate_sets[1].status == CandidateSetStatus.ACTIVE

    with pytest.raises(ValidationError):
        CandidateSet(
            candidate_set_id="bad",
            candidates=[
                CandidateItem(global_index=1, value="a", label="A"),
                CandidateItem(global_index=1, value="b", label="B"),
            ],
        )


def test_compact_for_llm_excludes_invalidated_details_and_limits_steps_and_candidates():
    context = DiagnosisContextManager.create("ses_1", "goal")
    for index in range(5):
        DiagnosisContextManager.apply_step_result(
            context,
            tool_name=f"tool_{index}",
            arguments={"path": "/tmp/trace"},
            result_summary={"summary": f"step {index}", "large_raw": "not automatically removed by helper"},
            evidence_id=f"ev_{index}",
            produced_params={f"p{index}": index},
        )
    invalidated = context.completed_steps.pop(1)
    invalidated.status = "invalidated"
    invalidated_revision = context.revision
    invalidated.revision_invalidated = invalidated_revision
    invalidated.invalidation_reason = "user changed step 2"
    context.invalidated_steps.append(invalidated)
    context.invalidated_evidence_ids.append("ev_1")
    context.effective_evidence_ids.remove("ev_1")
    context.param_provenance["p1"].invalidated = True
    context.known_params.pop("p1")

    candidate_set = CandidateSet(
        candidate_set_id="cset_1",
        type=CandidateSetType.RANK,
        candidates=[CandidateItem(global_index=i, value=i, label=f"Rank {i}") for i in range(1, 26)],
    )
    DiagnosisContextManager.add_candidate_set(context, candidate_set, primary=True)

    compact = compact_for_llm(context, stage="parameter_extraction")

    assert compact["stage"] == "parameter_extraction"
    assert len(compact["latest_completed_steps"]) == 3
    assert all(step["step_index"] != 2 for step in compact["latest_completed_steps"])
    assert "p1" not in compact["known_params"]
    assert "p1" not in compact["param_sources"]
    assert compact["active_candidate_set"]["candidate_count"] == 25
    assert len(compact["active_candidate_set"]["candidates"]) == 20
    assert compact["active_candidate_set"]["truncated"] is True
    assert compact["invalidated_summary"] == [
        {
            "step_index": 2,
            "tool_name": "tool_1",
            "revision_invalidated": invalidated_revision,
            "reason": "user changed step 2",
        }
    ]


def test_compact_for_sse_contains_user_visible_state():
    context = DiagnosisContextManager.create("ses_1", "goal", plan_id="plan_1")
    DiagnosisContextManager.add_or_update_param(context, "path", "/tmp/trace", ParamSource.USER_INITIAL)

    payload = compact_for_sse(context)

    assert payload["diagnosis_id"] == context.diagnosis_id
    assert payload["session_id"] == "ses_1"
    assert payload["plan_id"] == "plan_1"
    assert payload["known_params"] == {"path": "/tmp/trace"}
    assert payload["param_sources"]["path"]["source"] == ParamSource.USER_INITIAL


def test_schema_hash_is_stable_for_key_order():
    left = {"properties": {"a": {"type": "string"}, "b": {"type": "integer"}}}
    right = {"properties": {"b": {"type": "integer"}, "a": {"type": "string"}}}

    assert DiagnosisContextManager.schema_hash(left) == DiagnosisContextManager.schema_hash(right)


def test_context_json_is_plain_json_object():
    context = DiagnosisContextManager.create("ses_1", "goal", extracted={"path": "/tmp/trace"})
    raw = DiagnosisContextManager.to_json(context)
    parsed = json.loads(raw)

    assert parsed["diagnosis_id"] == context.diagnosis_id
    assert parsed["known_params"] == {"path": "/tmp/trace"}
