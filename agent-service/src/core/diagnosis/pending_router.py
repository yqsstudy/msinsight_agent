"""Route user input while diagnosis is pending or paused."""

from __future__ import annotations

import re
from typing import Iterable, Optional

from ...models.orchestration import PendingInput
from .models import DiagnosisContext, DiagnosisStatus, PendingInputIntent, PendingInputIntentType


class PendingInputRouter:
    """Classify user input before treating it as a pending answer."""

    RESTART_PATTERNS = ("重新分析", "重新开始", "从头", "换一个", "换个", "new trace", "restart")
    PAUSE_PATTERNS = ("暂停", "等会", "稍后", "不用继续", "先这样", "pause")
    CANCEL_PATTERNS = ("取消", "终止", "停止诊断", "cancel")
    STATUS_PATTERNS = ("状态", "进度", "到哪", "当前", "status")
    CONTINUE_PATTERNS = ("继续", "恢复", "接着", "resume", "continue")
    KNOWLEDGE_PATTERNS = ("是什么", "怎么", "如何", "文档", "用法", "说明", "原理")
    MODIFY_PATTERNS = ("重选", "修改", "改成", "换成", "回到", "第", "step")

    def route(
        self,
        user_input: str,
        pending: Optional[PendingInput],
        contexts: Iterable[DiagnosisContext],
    ) -> PendingInputIntent:
        text = (user_input or "").strip()
        context_list = list(contexts or [])
        active_context = self._context_for_pending(pending, context_list)

        if self._contains(text, self.CANCEL_PATTERNS):
            return PendingInputIntent(intent=PendingInputIntentType.CANCEL_DIAGNOSIS, confidence=0.95, diagnosis_id=getattr(active_context, "diagnosis_id", None), pending_id=getattr(pending, "id", None), reason="cancel intent")
        if self._contains(text, self.PAUSE_PATTERNS):
            return PendingInputIntent(intent=PendingInputIntentType.PAUSE_DIAGNOSIS, confidence=0.95, diagnosis_id=getattr(active_context, "diagnosis_id", None), pending_id=getattr(pending, "id", None), reason="pause intent")
        if self._contains(text, self.RESTART_PATTERNS) or self._has_new_path(text):
            return PendingInputIntent(intent=PendingInputIntentType.RESTART_DIAGNOSIS, confidence=0.9, diagnosis_id=getattr(active_context, "diagnosis_id", None), pending_id=getattr(pending, "id", None), extracted={"path": self._extract_path(text)}, reason="restart or new trace intent")
        if self._contains(text, self.STATUS_PATTERNS):
            return PendingInputIntent(intent=PendingInputIntentType.ASK_STATUS, confidence=0.85, diagnosis_id=getattr(active_context, "diagnosis_id", None), pending_id=getattr(pending, "id", None), reason="status intent")
        if self._looks_like_modify_previous_step(text):
            return PendingInputIntent(intent=PendingInputIntentType.MODIFY_PREVIOUS_STEP, confidence=0.75, diagnosis_id=getattr(active_context, "diagnosis_id", None), pending_id=getattr(pending, "id", None), target_step_index=self._extract_step_index(text), reason="modify previous step intent")

        paused_contexts = [ctx for ctx in context_list if ctx.status == DiagnosisStatus.PAUSED]
        if self._contains(text, self.CONTINUE_PATTERNS) and not pending:
            if len(paused_contexts) == 1:
                return PendingInputIntent(intent=PendingInputIntentType.RESUME_PAUSED, confidence=0.95, diagnosis_id=paused_contexts[0].diagnosis_id, reason="resume single paused diagnosis")
            if len(paused_contexts) > 1:
                latest = sorted(paused_contexts, key=lambda item: item.created_at, reverse=True)[0]
                return PendingInputIntent(intent=PendingInputIntentType.RESUME_PAUSED, confidence=0.8, diagnosis_id=latest.diagnosis_id, reason="resume latest paused diagnosis")

        if pending:
            if self._contains(text, self.KNOWLEDGE_PATTERNS) and self._is_complex_question(text):
                return PendingInputIntent(intent=PendingInputIntentType.SWITCH_TOPIC_OR_CHAT, confidence=0.7, diagnosis_id=getattr(active_context, "diagnosis_id", None), pending_id=pending.id, reason="knowledge/chat question during pending")
            return PendingInputIntent(intent=PendingInputIntentType.ANSWER_PENDING, confidence=0.8, diagnosis_id=getattr(active_context, "diagnosis_id", None), pending_id=pending.id, reason="default pending answer")

        if self._contains(text, self.CONTINUE_PATTERNS) and len(paused_contexts) > 1:
            latest = sorted(paused_contexts, key=lambda item: item.created_at, reverse=True)[0]
            return PendingInputIntent(intent=PendingInputIntentType.RESUME_PAUSED, confidence=0.8, diagnosis_id=latest.diagnosis_id, reason="resume latest paused diagnosis")

        return PendingInputIntent(intent=PendingInputIntentType.UNCLEAR, confidence=0.3, reason="no active pending or paused diagnosis target")

    def _context_for_pending(self, pending: Optional[PendingInput], contexts: list[DiagnosisContext]) -> Optional[DiagnosisContext]:
        if not pending:
            return None
        diagnosis_id = pending.metadata.get("diagnosis_id") if pending.metadata else None
        if diagnosis_id:
            for context in contexts:
                if context.diagnosis_id == diagnosis_id:
                    return context
        active = [context for context in contexts if context.status == DiagnosisStatus.ACTIVE]
        return active[0] if active else None

    def _contains(self, text: str, patterns: Iterable[str]) -> bool:
        lowered = text.lower()
        return any(pattern.lower() in lowered for pattern in patterns)

    def _has_new_path(self, text: str) -> bool:
        return bool(self._extract_path(text) and self._contains(text, ("分析", "trace", "profiling", "e2e")))

    def _extract_path(self, text: str) -> Optional[str]:
        match = re.search(r'([a-zA-Z]:\\[^\s"\'<>]+|/[^\s"\'<>]+)', text)
        return match.group(1).strip() if match else None

    def _looks_like_modify_previous_step(self, text: str) -> bool:
        return self._contains(text, self.MODIFY_PATTERNS) and bool(self._extract_step_index(text) or "参数" in text or "rank" in text or "path" in text)

    def _extract_step_index(self, text: str) -> Optional[int]:
        match = re.search(r'(?:第|step\s*)(\d+)', text, re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _is_complex_question(self, text: str) -> bool:
        return len(text) > 12 or any(mark in text for mark in ("？", "?", "怎么", "如何", "是什么"))
