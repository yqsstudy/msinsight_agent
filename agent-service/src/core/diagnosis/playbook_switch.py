"""Playbook switch handling for diagnosis contexts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .context import DiagnosisContextManager
from .models import DiagnosisContext, DiagnosisStatus


@dataclass(frozen=True)
class PlaybookSwitchResult:
    action: str
    old_diagnosis_id: str
    new_diagnosis_id: Optional[str] = None
    selected_playbook: Optional[str] = None
    migrated_params: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""


class PlaybookSwitchManager:
    """Supersede old effective path and start a clean playbook path."""

    CLEAR_SWITCH_MARKERS = ("切换到", "换成", "使用", "改用", "switch to")
    AMBIGUOUS_MARKERS = ("换个", "还有别的", "其他剧本", "另一个")

    def detect_switch_intent(self, user_input: str) -> str:
        text = (user_input or "").lower()
        if any(marker in text for marker in self.CLEAR_SWITCH_MARKERS) and "剧本" in text:
            return "explicit"
        if any(marker in text for marker in self.AMBIGUOUS_MARKERS):
            return "ambiguous"
        return "none"

    def switch_playbook(
        self,
        context: DiagnosisContext,
        new_user_input: str,
        selected_playbook: Optional[str] = None,
    ) -> PlaybookSwitchResult:
        old_id = context.diagnosis_id
        context.status = DiagnosisStatus.SUPERSEDED
        context.invalidated_evidence_ids.extend([eid for eid in context.effective_evidence_ids if eid not in context.invalidated_evidence_ids])
        context.effective_evidence_ids = []
        DiagnosisContextManager.increment_revision(context)

        new_context = DiagnosisContextManager.create(
            session_id=context.session_id,
            plan_id=context.plan_id,
            root_message=new_user_input,
            extracted={"selected_playbook": selected_playbook} if selected_playbook else {},
        )
        new_context.selected_playbook = selected_playbook
        return PlaybookSwitchResult(
            action="switch",
            old_diagnosis_id=old_id,
            new_diagnosis_id=new_context.diagnosis_id,
            selected_playbook=selected_playbook,
            migrated_params={},
            reason="old path superseded; parameters are not migrated across playbooks",
        ), new_context

    def clarification(self, context: DiagnosisContext, reason: str = "ambiguous_playbook_switch") -> PlaybookSwitchResult:
        return PlaybookSwitchResult(action="clarify", old_diagnosis_id=context.diagnosis_id, reason=reason)
