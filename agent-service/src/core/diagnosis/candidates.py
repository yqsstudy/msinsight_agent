"""CandidateSet lifecycle management for diagnosis contexts."""

from __future__ import annotations

import re
import uuid
from typing import Any, Iterable, Optional

from ...observability.metrics import record_diagnosis_candidate_set
from .context import DiagnosisContextManager
from .models import (
    CandidateItem,
    CandidateSet,
    CandidateSetStatus,
    CandidateSetType,
    ConfidenceLevel,
    DiagnosisContext,
    ParamSource,
)


class CandidateSetManager:
    """Manage stable candidate selection across turns."""

    ORDINAL_WORDS = {
        "第一个": 1,
        "第一": 1,
        "一个": 1,
        "第二个": 2,
        "第二": 2,
        "二个": 2,
        "第三个": 3,
        "第三": 3,
        "三个": 3,
        "第四个": 4,
        "第四": 4,
        "四个": 4,
        "第五个": 5,
        "第五": 5,
        "五个": 5,
    }

    def create_candidate_set(
        self,
        context: DiagnosisContext,
        type: CandidateSetType | str,
        candidates: Iterable[Any],
        source_step_index: Optional[int] = None,
        source_tool_name: Optional[str] = None,
        source_evidence_id: Optional[str] = None,
        primary: bool = True,
        candidate_set_id: Optional[str] = None,
    ) -> CandidateSet:
        start_index = self._next_global_index(context)
        items = [self._to_candidate_item(candidate, start_index + offset) for offset, candidate in enumerate(candidates)]
        candidate_set = CandidateSet(
            candidate_set_id=candidate_set_id or f"cset_{uuid.uuid4().hex}",
            type=type,
            source_step_index=source_step_index,
            source_tool_name=source_tool_name,
            source_evidence_id=source_evidence_id,
            candidates=items,
            created_revision=context.revision,
        )
        DiagnosisContextManager.add_candidate_set(context, candidate_set, primary=primary)
        record_diagnosis_candidate_set("created", str(candidate_set.type))
        return candidate_set

    def resolve_selection(
        self,
        user_input: Any,
        context: DiagnosisContext,
        candidate_set_id: Optional[str] = None,
    ) -> CandidateItem:
        candidate_set = self._target_candidate_set(context, candidate_set_id)
        if not candidate_set:
            raise ValueError("No active CandidateSet is available for selection")
        if candidate_set.status != CandidateSetStatus.ACTIVE:
            raise ValueError(f"CandidateSet {candidate_set.candidate_set_id} is not active")
        index = self._parse_selection_index(user_input)
        if index is None:
            raise ValueError(f"Cannot resolve candidate selection from input: {user_input}")
        for candidate in candidate_set.candidates:
            if candidate.global_index == index:
                return candidate
        # If the user says “第二个”, bind to active set local order when global index differs.
        if 1 <= index <= len(candidate_set.candidates):
            return candidate_set.candidates[index - 1]
        raise ValueError(f"Candidate index {index} is not in CandidateSet {candidate_set.candidate_set_id}")

    def select_candidate(
        self,
        context: DiagnosisContext,
        candidate_set_id: str,
        global_index: int,
        param_key: Optional[str] = None,
    ) -> CandidateItem:
        candidate_set = self._target_candidate_set(context, candidate_set_id)
        if not candidate_set:
            raise ValueError(f"CandidateSet not found: {candidate_set_id}")
        if candidate_set.status != CandidateSetStatus.ACTIVE:
            raise ValueError(f"CandidateSet {candidate_set_id} is not active")
        candidate = next((item for item in candidate_set.candidates if item.global_index == global_index), None)
        if not candidate:
            raise ValueError(f"Candidate index {global_index} is not in CandidateSet {candidate_set_id}")
        candidate_set.status = CandidateSetStatus.SELECTED
        candidate_set.selected_value = candidate.value
        if context.primary_candidate_set_id == candidate_set_id:
            context.primary_candidate_set_id = None
        if param_key:
            DiagnosisContextManager.add_or_update_param(
                context,
                key=param_key,
                value=candidate.value,
                source=ParamSource.USER_SELECTION,
                confidence=ConfidenceLevel.HIGH,
                source_step_index=candidate_set.source_step_index,
                source_tool_name=candidate_set.source_tool_name,
                source_evidence_id=candidate_set.source_evidence_id,
                user_confirmed=True,
                increment_revision=False,
            )
        DiagnosisContextManager.increment_revision(context)
        record_diagnosis_candidate_set("selected", str(candidate_set.type))
        return candidate

    def invalidate_by_source_step(self, context: DiagnosisContext, step_index: int) -> list[CandidateSet]:
        invalidated = []
        revision = DiagnosisContextManager.increment_revision(context)
        for candidate_set in context.candidate_sets:
            if candidate_set.source_step_index is not None and candidate_set.source_step_index >= step_index:
                candidate_set.status = CandidateSetStatus.INVALIDATED
                candidate_set.invalidated_revision = revision
                invalidated.append(candidate_set)
                record_diagnosis_candidate_set("invalidated", str(candidate_set.type))
                if context.primary_candidate_set_id == candidate_set.candidate_set_id:
                    context.primary_candidate_set_id = None
        return invalidated

    def active_primary(self, context: DiagnosisContext) -> Optional[CandidateSet]:
        return self._target_candidate_set(context, context.primary_candidate_set_id)

    def _target_candidate_set(self, context: DiagnosisContext, candidate_set_id: Optional[str]) -> Optional[CandidateSet]:
        target_id = candidate_set_id or context.primary_candidate_set_id
        if not target_id:
            return None
        for candidate_set in context.candidate_sets:
            if candidate_set.candidate_set_id == target_id:
                return candidate_set
        return None

    def _next_global_index(self, context: DiagnosisContext) -> int:
        max_index = 0
        for candidate_set in context.candidate_sets:
            for candidate in candidate_set.candidates:
                max_index = max(max_index, candidate.global_index)
        return max_index + 1

    def _to_candidate_item(self, candidate: Any, global_index: int) -> CandidateItem:
        if isinstance(candidate, CandidateItem):
            return candidate.model_copy(update={"global_index": global_index})
        if isinstance(candidate, dict):
            value = candidate.get("value") or candidate.get("id") or candidate.get("playbook_id") or candidate.get("name") or candidate
            label = str(candidate.get("label") or candidate.get("name") or candidate.get("id") or candidate.get("playbook_id") or value)
            description = candidate.get("description") or candidate.get("summary")
            return CandidateItem(global_index=global_index, value=value, label=label, description=description, metadata=dict(candidate))
        return CandidateItem(global_index=global_index, value=candidate, label=str(candidate), metadata={})

    def _parse_selection_index(self, user_input: Any) -> Optional[int]:
        if isinstance(user_input, int):
            return user_input
        if isinstance(user_input, dict):
            for key in ("global_index", "index", "candidate_index", "value"):
                value = user_input.get(key)
                if isinstance(value, int):
                    return value
                if isinstance(value, str) and value.isdigit():
                    return int(value)
        text = str(user_input).strip()
        if text.isdigit():
            return int(text)
        for word, value in self.ORDINAL_WORDS.items():
            if word in text:
                return value
        match = re.search(r'(?:第|#)?\s*(\d+)\s*(?:个|项|号)?', text)
        return int(match.group(1)) if match else None
