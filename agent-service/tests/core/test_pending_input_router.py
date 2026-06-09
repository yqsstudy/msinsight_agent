import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.core.diagnosis import DiagnosisContextManager
from src.core.diagnosis.models import DiagnosisStatus, PendingInputIntentType
from src.core.diagnosis.pending_router import PendingInputRouter
from src.models.orchestration import PendingInput


def pending(diagnosis_id="diag_1"):
    return PendingInput(
        id="pin_1",
        session_id="ses_1",
        input_type="params",
        question="need rank",
        metadata={"diagnosis_id": diagnosis_id, "agent_type": "diagnosis"},
    )


def active_context():
    ctx = DiagnosisContextManager.create("ses_1", "goal", diagnosis_id="diag_1")
    return ctx


def test_pending_restart_with_new_trace_is_not_treated_as_answer():
    router = PendingInputRouter()
    intent = router.route("重新分析 /data/new_trace", pending(), [active_context()])

    assert intent.intent == PendingInputIntentType.RESTART_DIAGNOSIS
    assert intent.diagnosis_id == "diag_1"
    assert intent.extracted["path"] == "/data/new_trace"


def test_pending_pause_preserves_context_target():
    router = PendingInputRouter()
    intent = router.route("不用继续了，先暂停", pending(), [active_context()])

    assert intent.intent == PendingInputIntentType.PAUSE_DIAGNOSIS
    assert intent.pending_id == "pin_1"
    assert intent.diagnosis_id == "diag_1"


def test_pending_knowledge_question_switches_topic():
    router = PendingInputRouter()
    intent = router.route("msprof 怎么分析通信耗时？", pending(), [active_context()])

    assert intent.intent == PendingInputIntentType.SWITCH_TOPIC_OR_CHAT


def test_pending_plain_value_answers_pending():
    router = PendingInputRouter()
    intent = router.route("rank 3", pending(), [active_context()])

    assert intent.intent == PendingInputIntentType.ANSWER_PENDING


def test_multiple_paused_bare_continue_chooses_latest_created():
    router = PendingInputRouter()
    older = DiagnosisContextManager.create("ses_1", "old", diagnosis_id="diag_old")
    older.status = DiagnosisStatus.PAUSED
    newer = DiagnosisContextManager.create("ses_1", "new", diagnosis_id="diag_new")
    newer.status = DiagnosisStatus.PAUSED
    newer.created_at = older.created_at + timedelta(seconds=10)

    intent = router.route("继续", None, [older, newer])

    assert intent.intent == PendingInputIntentType.RESUME_PAUSED
    assert intent.diagnosis_id == "diag_new"


def test_modify_previous_step_is_detected():
    router = PendingInputRouter()
    intent = router.route("回到第2步，把 rank 改成 4", pending(), [active_context()])

    assert intent.intent == PendingInputIntentType.MODIFY_PREVIOUS_STEP
    assert intent.target_step_index == 2


def test_status_intent_is_detected():
    router = PendingInputRouter()
    intent = router.route("当前进度到哪了", pending(), [active_context()])

    assert intent.intent == PendingInputIntentType.ASK_STATUS
