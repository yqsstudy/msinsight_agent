import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.core.diagnosis import CandidateItem, CandidateSet, CandidateSetStatus, DiagnosisContextManager, InvalidationEngine
from src.core.diagnosis.models import PendingStepState, StepStatus


def build_context_with_steps():
    context = DiagnosisContextManager.create("ses_1", "goal")
    for index in range(1, 6):
        DiagnosisContextManager.apply_step_result(
            context,
            tool_name=f"tool_{index}",
            arguments={"path": "/tmp/trace"},
            result_summary={"summary": f"step {index}"},
            evidence_id=f"ev_{index}",
            produced_params={f"p{index}": index},
        )
    return context


def test_invalidate_from_step_linearly_invalidates_downstream_steps_params_and_evidence():
    context = build_context_with_steps()
    engine = InvalidationEngine()

    invalidated = engine.invalidate_from_step(context, 2, "user changed step 2 params")

    assert [step.step_index for step in invalidated] == [2, 3, 4, 5]
    assert [step.step_index for step in context.completed_steps] == [1]
    assert [step.step_index for step in context.invalidated_steps] == [2, 3, 4, 5]
    assert all(step.status == StepStatus.INVALIDATED for step in context.invalidated_steps)
    assert context.effective_evidence_ids == ["ev_1"]
    assert context.invalidated_evidence_ids == ["ev_2", "ev_3", "ev_4", "ev_5"]
    assert context.known_params == {"p1": 1}
    assert context.param_provenance["p2"].invalidated is True
    assert context.param_provenance["p5"].revision_invalidated == context.revision
    assert context.current_step_index == 1
    assert context.current_tool_name == "tool_1"


def test_invalidate_from_step_invalidates_candidate_sets_from_affected_steps():
    context = build_context_with_steps()
    cset_before = CandidateSet(
        candidate_set_id="cset_before",
        source_step_index=1,
        candidates=[CandidateItem(global_index=1, value="a", label="A")],
    )
    cset_after = CandidateSet(
        candidate_set_id="cset_after",
        source_step_index=3,
        candidates=[CandidateItem(global_index=2, value="b", label="B")],
    )
    DiagnosisContextManager.add_candidate_set(context, cset_before, primary=True)
    DiagnosisContextManager.add_candidate_set(context, cset_after, primary=True)

    InvalidationEngine().invalidate_from_step(context, 2, "rollback")

    assert context.candidate_sets[0].status == CandidateSetStatus.SUPERSEDED
    assert context.candidate_sets[1].status == CandidateSetStatus.INVALIDATED
    assert context.primary_candidate_set_id is None


def test_invalidate_from_step_clears_pending_when_current_step_is_affected():
    context = build_context_with_steps()
    DiagnosisContextManager.set_pending(context, PendingStepState(
        pending_id="pin_1",
        resume_action="continue_mcp_with_args",
        tool_name="tool_5",
        required_missing=["rank"],
    ))
    context.current_step_index = 5

    InvalidationEngine().invalidate_from_step(context, 3, "rollback")

    assert context.pending is None


def test_invalidate_from_step_noop_for_unaffected_future_step():
    context = build_context_with_steps()
    revision = context.revision

    result = InvalidationEngine().invalidate_from_step(context, 99, "noop")

    assert result == []
    assert context.revision == revision
    assert len(context.completed_steps) == 5
