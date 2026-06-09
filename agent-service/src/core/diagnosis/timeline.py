"""Simplified diagnosis timeline projection from audit events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .models import DiagnosisAuditEvent


@dataclass(frozen=True)
class DiagnosisTimelineItem:
    id: str
    diagnosis_id: Optional[str]
    event_type: str
    revision: Optional[int]
    title: str
    detail: str
    created_at: str
    payload: Dict[str, Any]


class DiagnosisTimelineBuilder:
    """Build a lightweight timeline suitable for UI/debug views."""

    TITLE_MAP = {
        "param_added": "参数新增",
        "param_updated": "参数更新",
        "param_invalidated": "参数失效",
        "step_started": "步骤开始",
        "step_completed": "步骤完成",
        "step_failed": "步骤失败",
        "step_invalidated": "步骤失效",
        "pending_created": "等待用户输入",
        "pending_resolved": "用户输入已解决",
        "pending_paused": "诊断暂停",
        "candidate_set_created": "候选集创建",
        "candidate_set_selected": "候选项选择",
        "candidate_set_invalidated": "候选集失效",
        "operation_queued": "操作入队",
        "operation_running": "操作执行中",
        "operation_completed": "操作完成",
        "operation_stale": "操作过期",
        "rollback_detected": "检测到回退",
        "rollback_applied": "回退已应用",
        "reconciliation_attempted": "MCP 状态协调",
        "reconciliation_succeeded": "MCP 状态协调成功",
        "reconciliation_failed": "MCP 状态协调失败",
        "schema_drift_detected": "Schema 变化",
        "schema_migrated": "Schema 已迁移",
        "playbook_switched": "剧本已切换",
        "report_generated": "报告已生成",
    }

    def build(self, events: Iterable[DiagnosisAuditEvent]) -> List[DiagnosisTimelineItem]:
        return [self._to_item(event) for event in sorted(events, key=lambda item: item.created_at)]

    def _to_item(self, event: DiagnosisAuditEvent) -> DiagnosisTimelineItem:
        title = self.TITLE_MAP.get(event.event_type, event.event_type)
        detail = self._detail(event.payload)
        return DiagnosisTimelineItem(
            id=event.id,
            diagnosis_id=event.diagnosis_id,
            event_type=event.event_type,
            revision=event.revision,
            title=title,
            detail=detail,
            created_at=event.created_at.isoformat(),
            payload=event.payload,
        )

    def _detail(self, payload: Dict[str, Any]) -> str:
        for key in ("reason", "tool_name", "operation_id", "key", "candidate_set_id", "report_id", "status"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
        return ""
