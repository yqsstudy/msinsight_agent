"""MCP blocked/stale reconciliation for diagnosis contexts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ...observability.metrics import record_diagnosis_reconciliation
from .context import DiagnosisContextManager
from .invalidation import InvalidationEngine
from .models import DiagnosisContext, ReconciliationStatus


@dataclass(frozen=True)
class ReconciliationResult:
    action: str
    reason: str
    required_tool: Optional[str] = None
    required_arguments: Dict[str, Any] = field(default_factory=dict)
    invalidated_from_step: Optional[int] = None
    exceeded_limit: bool = False


class ReconciliationEngine:
    """Interpret MCP execution-state conflicts and choose a deterministic recovery."""

    BLOCKED_MARKERS = ("blocked", "execution blocked", "prerequisite_missing", "requires", "前置", "依赖")
    STALE_MARKERS = ("stale", "context_changed", "上下文", "过期")

    def __init__(self, invalidation_engine: Optional[InvalidationEngine] = None):
        self.invalidation_engine = invalidation_engine or InvalidationEngine()

    def reconcile(self, context: DiagnosisContext, mcp_result: Any, current_tool: str, args: Dict[str, Any]) -> ReconciliationResult:
        reason = self._reason(mcp_result)
        if not self._needs_reconciliation(reason):
            return ReconciliationResult(action="none", reason="mcp_result_does_not_require_reconciliation")

        attempts_for_reason = context.reconciliation_state.attempts_by_reason.get(reason, 0)
        if attempts_for_reason >= 1 or context.reconciliation_state.consecutive_attempts >= 2:
            context.reconciliation_state.status = ReconciliationStatus.SUSPENDED
            context.reconciliation_state.last_error = reason
            DiagnosisContextManager.increment_revision(context)
            record_diagnosis_reconciliation("suspend", failed_reason=reason)
            return ReconciliationResult(action="suspend", reason=reason, exceeded_limit=True)

        context.reconciliation_state.status = ReconciliationStatus.IN_PROGRESS
        context.reconciliation_state.current_reason = reason
        context.reconciliation_state.consecutive_attempts += 1
        context.reconciliation_state.attempts_by_reason[reason] = attempts_for_reason + 1
        DiagnosisContextManager.increment_revision(context)

        required = self._required_step(mcp_result)
        if required and required.get("tool_name"):
            step_index = self._step_index_for_tool(context, required.get("tool_name"))
            if step_index is not None:
                self.invalidation_engine.invalidate_from_step(context, step_index, f"mcp_reconciliation:{reason}")
                record_diagnosis_reconciliation("execute_required_step")
                return ReconciliationResult(
                    action="execute_required_step",
                    reason=reason,
                    required_tool=required.get("tool_name"),
                    required_arguments=required.get("arguments") or {},
                    invalidated_from_step=step_index,
                )
            record_diagnosis_reconciliation("execute_required_step")
            return ReconciliationResult(
                action="execute_required_step",
                reason=reason,
                required_tool=required.get("tool_name"),
                required_arguments=required.get("arguments") or {},
            )

        if self._is_stale(reason):
            step_index = self._step_index_for_tool(context, current_tool)
            if step_index is not None:
                self.invalidation_engine.invalidate_from_step(context, step_index, f"mcp_reconciliation:{reason}")
                record_diagnosis_reconciliation("retry_current_step")
                return ReconciliationResult(action="retry_current_step", reason=reason, required_tool=current_tool, required_arguments=args, invalidated_from_step=step_index)

        record_diagnosis_reconciliation("suspend", failed_reason=reason)
        return ReconciliationResult(action="suspend", reason=reason)

    def mark_succeeded(self, context: DiagnosisContext) -> None:
        context.reconciliation_state.status = ReconciliationStatus.SUCCEEDED
        context.reconciliation_state.current_reason = None
        context.reconciliation_state.consecutive_attempts = 0
        DiagnosisContextManager.increment_revision(context)

    def mark_failed(self, context: DiagnosisContext, error: str) -> None:
        context.reconciliation_state.status = ReconciliationStatus.FAILED
        context.reconciliation_state.last_error = error
        DiagnosisContextManager.increment_revision(context)

    def _reason(self, mcp_result: Any) -> str:
        if isinstance(mcp_result, dict):
            for key in ("reason", "error", "status", "text", "message"):
                value = mcp_result.get(key)
                if value:
                    return str(value).lower()
        text = getattr(mcp_result, "text", None) or getattr(mcp_result, "error", None) or getattr(mcp_result, "status", None)
        return str(text or "").lower()

    def _needs_reconciliation(self, reason: str) -> bool:
        return self._is_blocked(reason) or self._is_stale(reason)

    def _is_blocked(self, reason: str) -> bool:
        return any(marker in reason for marker in self.BLOCKED_MARKERS)

    def _is_stale(self, reason: str) -> bool:
        return any(marker in reason for marker in self.STALE_MARKERS)

    def _required_step(self, mcp_result: Any) -> Optional[Dict[str, Any]]:
        raw = mcp_result if isinstance(mcp_result, dict) else getattr(mcp_result, "raw", {})
        if not isinstance(raw, dict):
            return None
        for container in (raw, raw.get("parsedContent"), raw.get("structuredContent"), raw.get("result")):
            if isinstance(container, dict):
                required = container.get("required_step") or container.get("required") or container.get("prerequisite")
                if isinstance(required, dict):
                    return required
        return None

    def _step_index_for_tool(self, context: DiagnosisContext, tool_name: Optional[str]) -> Optional[int]:
        if not tool_name:
            return None
        for step in context.completed_steps:
            if step.tool_name == tool_name:
                return step.step_index
        return None
