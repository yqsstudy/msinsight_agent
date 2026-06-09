"""会话存储 - 基于SQLite的会话持久化"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import List, Optional, Dict, Any, TYPE_CHECKING
import os
import uuid

from ..models import Session, Message, AnalysisContext
from ..models.evidence import Evidence, EvidenceType, EvidenceConfidence, CreateEvidenceRequest
from ..models.orchestration import (
    ExecutionPlan,
    ExecutionPlanStatus,
    ExecutionStep,
    ExecutionStepStatus,
    ExecutionStepType,
    PendingInput,
    PendingInputOption,
)
if TYPE_CHECKING:
    from ..core.diagnosis.models import DiagnosisAuditEvent, DiagnosisContext, DiagnosisOperation


def _diagnosis_models():
    from ..core.diagnosis.models import DiagnosisAuditEvent, DiagnosisContext, DiagnosisOperation, OperationStatus

    return DiagnosisAuditEvent, DiagnosisContext, DiagnosisOperation, OperationStatus


class SessionStore:
    """会话存储"""

    def __init__(self, storage_path: str = "./sessions"):
        if storage_path == ":memory:" or storage_path.endswith(".db"):
            self.db_path = storage_path
            self.storage_path = os.path.dirname(storage_path)
        else:
            self.storage_path = storage_path
            self.db_path = os.path.join(storage_path, "sessions.db")
        self._ensure_storage()

    def _ensure_storage(self):
        """确保存储目录和数据库存在"""
        if self.storage_path:
            os.makedirs(self.storage_path, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                state TEXT DEFAULT 'IDLE',
                context TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                metadata TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS execution_plans (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_message_id TEXT,
                intent TEXT NOT NULL,
                status TEXT NOT NULL,
                goal TEXT,
                current_step_id TEXT,
                evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_execution_plans_session ON execution_plans(session_id)")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS execution_steps (
                id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                input_json TEXT NOT NULL DEFAULT '{}',
                output_json TEXT,
                evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                error_json TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                started_at TEXT,
                completed_at TEXT,
                elapsed_ms INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (plan_id) REFERENCES execution_plans(id),
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_execution_steps_plan ON execution_steps(plan_id)")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                plan_id TEXT,
                step_id TEXT,
                type TEXT NOT NULL,
                source TEXT NOT NULL,
                content TEXT NOT NULL,
                summary TEXT,
                confidence TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        self._ensure_column(cursor, "evidence", "plan_id", "TEXT")
        self._ensure_column(cursor, "evidence", "step_id", "TEXT")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_session ON evidence(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_plan ON evidence(plan_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(type)")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_inputs (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                plan_id TEXT,
                step_id TEXT,
                input_type TEXT NOT NULL,
                question TEXT NOT NULL,
                reason TEXT,
                options_json TEXT NOT NULL DEFAULT '[]',
                recommended_value TEXT,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        self._ensure_column(cursor, "pending_inputs", "plan_id", "TEXT")
        self._ensure_column(cursor, "pending_inputs", "step_id", "TEXT")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                plan_id TEXT,
                format TEXT NOT NULL,
                content TEXT NOT NULL,
                evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        self._ensure_column(cursor, "reports", "plan_id", "TEXT")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                report_id TEXT,
                adopted INTEGER,
                comment TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                FOREIGN KEY (report_id) REFERENCES reports(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS diagnosis_contexts (
                diagnosis_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL,
                context_json TEXT NOT NULL,
                revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_diagnosis_contexts_session_status
            ON diagnosis_contexts(session_id, status)
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS diagnosis_operations (
                operation_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                diagnosis_id TEXT,
                idempotency_key TEXT,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                target_pending_id TEXT,
                expected_revision INTEGER,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                error TEXT
            )
        """)
        self._ensure_column(cursor, "diagnosis_operations", "error", "TEXT")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_diagnosis_operations_session_status
            ON diagnosis_operations(session_id, status)
        """)
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_diagnosis_operations_session_idempotency
            ON diagnosis_operations(session_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS diagnosis_audit_events (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                diagnosis_id TEXT,
                event_type TEXT NOT NULL,
                revision INTEGER,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_diagnosis_audit_session_diag
            ON diagnosis_audit_events(session_id, diagnosis_id, created_at)
        """)

        conn.commit()
        conn.close()

    def _ensure_column(self, cursor: sqlite3.Cursor, table: str, column: str, definition: str) -> None:
        cursor.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def save(self, session: Session):
        """保存会话"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # 保存会话基本信息
        cursor.execute("""
            INSERT OR REPLACE INTO sessions (id, created_at, updated_at, state, context)
            VALUES (?, ?, ?, ?, ?)
        """, (
            session.id,
            session.created_at.isoformat(),
            session.updated_at.isoformat(),
            session.state,
            json.dumps(self._context_to_dict(session.context))
        ))

        # 保存消息
        for msg in session.messages:
            cursor.execute("""
                INSERT OR REPLACE INTO messages (id, session_id, role, content, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                msg.id,
                session.id,
                msg.role,
                msg.content,
                msg.timestamp.isoformat(),
                json.dumps(msg.metadata)
            ))

        conn.commit()
        conn.close()

    def load(self, session_id: str) -> Optional[Session]:
        """加载会话"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return None

        session = Session(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            state=row["state"],
            context=self._dict_to_context(json.loads(row["context"]))
        )

        # 加载消息
        cursor.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp",
            (session_id,)
        )
        for msg_row in cursor.fetchall():
            session.messages.append(Message(
                id=msg_row["id"],
                role=msg_row["role"],
                content=msg_row["content"],
                timestamp=datetime.fromisoformat(msg_row["timestamp"]),
                metadata=json.loads(msg_row["metadata"])
            ))

        conn.close()
        return session

    def list_all(self, limit: int = 20) -> List[Session]:
        """列出所有会话"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, created_at, updated_at, state
            FROM sessions
            ORDER BY updated_at DESC
            LIMIT ?
        """, (limit,))

        sessions = []
        for row in cursor.fetchall():
            sessions.append(Session(
                id=row["id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                state=row["state"],
                messages=[],
                context=AnalysisContext()
            ))

        conn.close()
        return sessions

    def delete(self, session_id: str) -> bool:
        """删除会话"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def create_execution_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """创建或更新执行计划。"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO execution_plans (
                id, session_id, user_message_id, intent, status, goal,
                current_step_id, evidence_ids_json, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            plan.id,
            plan.session_id,
            plan.user_message_id,
            plan.intent.value,
            plan.status.value,
            plan.goal,
            plan.current_step_id,
            json.dumps(plan.evidence_ids, ensure_ascii=False),
            json.dumps(plan.metadata, ensure_ascii=False),
            plan.created_at.isoformat(),
            plan.updated_at.isoformat(),
        ))
        for step in plan.steps:
            self._upsert_execution_step(cursor, step)
        conn.commit()
        conn.close()
        return plan

    def update_execution_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        plan.updated_at = datetime.utcnow()
        return self.create_execution_plan(plan)

    def get_execution_plan(self, plan_id: str) -> Optional[ExecutionPlan]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM execution_plans WHERE id = ?", (plan_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        plan = self._row_to_execution_plan(row)
        plan.steps = self._list_execution_steps_with_cursor(cursor, plan.id)
        conn.close()
        return plan

    def list_execution_plans(self, session_id: str) -> List[ExecutionPlan]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM execution_plans
            WHERE session_id = ?
            ORDER BY created_at
        """, (session_id,))
        plans = [self._row_to_execution_plan(row) for row in cursor.fetchall()]
        for plan in plans:
            plan.steps = self._list_execution_steps_with_cursor(cursor, plan.id)
        conn.close()
        return plans

    def create_execution_step(self, step: ExecutionStep) -> ExecutionStep:
        conn = self._get_connection()
        cursor = conn.cursor()
        self._upsert_execution_step(cursor, step)
        conn.commit()
        conn.close()
        return step

    def update_execution_step(self, step: ExecutionStep) -> ExecutionStep:
        step.updated_at = datetime.utcnow()
        return self.create_execution_step(step)

    def list_execution_steps(self, plan_id: str) -> List[ExecutionStep]:
        conn = self._get_connection()
        cursor = conn.cursor()
        steps = self._list_execution_steps_with_cursor(cursor, plan_id)
        conn.close()
        return steps

    def append_plan_evidence(self, plan_id: str, evidence_id: str) -> None:
        plan = self.get_execution_plan(plan_id)
        if not plan or evidence_id in plan.evidence_ids:
            return
        plan.evidence_ids.append(evidence_id)
        self.update_execution_plan(plan)

    def append_step_evidence(self, step_id: str, evidence_id: str) -> None:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM execution_steps WHERE id = ?", (step_id,))
        row = cursor.fetchone()
        if row:
            step = self._row_to_execution_step(row)
            if evidence_id not in step.evidence_ids:
                step.evidence_ids.append(evidence_id)
                self._upsert_execution_step(cursor, step)
        conn.commit()
        conn.close()

    def create_diagnosis_context(self, context: DiagnosisContext) -> DiagnosisContext:
        """创建或替换诊断上下文。"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO diagnosis_contexts (
                diagnosis_id, session_id, status, context_json, revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            context.diagnosis_id,
            context.session_id,
            self._enum_value(context.status),
            context.model_dump_json(),
            context.revision,
            context.created_at.isoformat(),
            context.updated_at.isoformat(),
        ))
        conn.commit()
        conn.close()
        return context

    def update_diagnosis_context(self, context: DiagnosisContext) -> DiagnosisContext:
        """更新诊断上下文。"""
        context.updated_at = datetime.utcnow()
        return self.create_diagnosis_context(context)

    def get_diagnosis_context(self, diagnosis_id: str) -> Optional[DiagnosisContext]:
        """按 diagnosis_id 获取诊断上下文。"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM diagnosis_contexts WHERE diagnosis_id = ?", (diagnosis_id,))
        row = cursor.fetchone()
        conn.close()
        return self._row_to_diagnosis_context(row) if row else None

    def get_active_diagnosis_context(self, session_id: str) -> Optional[DiagnosisContext]:
        """获取 session 最新 active 诊断上下文。"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM diagnosis_contexts
            WHERE session_id = ? AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 1
        """, (session_id,))
        row = cursor.fetchone()
        conn.close()
        return self._row_to_diagnosis_context(row) if row else None

    def list_diagnosis_contexts(self, session_id: str, status: Optional[str] = None) -> List[DiagnosisContext]:
        """列出 session 下诊断上下文。"""
        conn = self._get_connection()
        cursor = conn.cursor()
        if status:
            cursor.execute("""
                SELECT * FROM diagnosis_contexts
                WHERE session_id = ? AND status = ?
                ORDER BY created_at DESC
            """, (session_id, status))
        else:
            cursor.execute("""
                SELECT * FROM diagnosis_contexts
                WHERE session_id = ?
                ORDER BY created_at DESC
            """, (session_id,))
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_diagnosis_context(row) for row in rows]

    def create_diagnosis_operation(self, operation: DiagnosisOperation) -> DiagnosisOperation:
        """创建诊断操作；同一 idempotency_key 返回既有操作。"""
        if operation.idempotency_key:
            existing = self.find_operation_by_idempotency_key(operation.session_id, operation.idempotency_key)
            if existing and existing.operation_id != operation.operation_id:
                return existing
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO diagnosis_operations (
                operation_id, session_id, diagnosis_id, idempotency_key, type, status,
                payload_json, target_pending_id, expected_revision, created_at,
                started_at, completed_at, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            operation.operation_id,
            operation.session_id,
            operation.diagnosis_id,
            operation.idempotency_key,
            self._enum_value(operation.type),
            self._enum_value(operation.status),
            json.dumps(operation.payload, ensure_ascii=False),
            operation.target_pending_id,
            operation.expected_revision,
            operation.created_at.isoformat(),
            operation.started_at.isoformat() if operation.started_at else None,
            operation.completed_at.isoformat() if operation.completed_at else None,
            operation.error,
        ))
        conn.commit()
        conn.close()
        return operation

    def update_diagnosis_operation(self, operation: DiagnosisOperation) -> DiagnosisOperation:
        """更新诊断操作。"""
        return self.create_diagnosis_operation(operation)

    def get_diagnosis_operation(self, operation_id: str) -> Optional[DiagnosisOperation]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM diagnosis_operations WHERE operation_id = ?", (operation_id,))
        row = cursor.fetchone()
        conn.close()
        return self._row_to_diagnosis_operation(row) if row else None

    def find_operation_by_idempotency_key(self, session_id: str, idempotency_key: str) -> Optional[DiagnosisOperation]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM diagnosis_operations
            WHERE session_id = ? AND idempotency_key = ?
            LIMIT 1
        """, (session_id, idempotency_key))
        row = cursor.fetchone()
        conn.close()
        return self._row_to_diagnosis_operation(row) if row else None

    def list_queued_operations(self, session_id: str) -> List[DiagnosisOperation]:
        _, _, _, OperationStatus = _diagnosis_models()
        return self.list_diagnosis_operations(session_id, status=OperationStatus.QUEUED)

    def list_diagnosis_operations(self, session_id: str, status: Optional[str] = None) -> List[DiagnosisOperation]:
        conn = self._get_connection()
        cursor = conn.cursor()
        if status:
            cursor.execute("""
                SELECT * FROM diagnosis_operations
                WHERE session_id = ? AND status = ?
                ORDER BY created_at ASC
            """, (session_id, self._enum_value(status)))
        else:
            cursor.execute("""
                SELECT * FROM diagnosis_operations
                WHERE session_id = ?
                ORDER BY created_at ASC
            """, (session_id,))
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_diagnosis_operation(row) for row in rows]

    def create_diagnosis_audit_event(self, event: DiagnosisAuditEvent) -> DiagnosisAuditEvent:
        """创建诊断审计事件。"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO diagnosis_audit_events (
                id, session_id, diagnosis_id, event_type, revision, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            event.id,
            event.session_id,
            event.diagnosis_id,
            event.event_type,
            event.revision,
            json.dumps(event.payload, ensure_ascii=False),
            event.created_at.isoformat(),
        ))
        conn.commit()
        conn.close()
        return event

    def list_diagnosis_audit_events(self, session_id: str, diagnosis_id: Optional[str] = None) -> List[DiagnosisAuditEvent]:
        conn = self._get_connection()
        cursor = conn.cursor()
        if diagnosis_id:
            cursor.execute("""
                SELECT * FROM diagnosis_audit_events
                WHERE session_id = ? AND diagnosis_id = ?
                ORDER BY created_at ASC
            """, (session_id, diagnosis_id))
        else:
            cursor.execute("""
                SELECT * FROM diagnosis_audit_events
                WHERE session_id = ?
                ORDER BY created_at ASC
            """, (session_id,))
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_diagnosis_audit_event(row) for row in rows]

    def create_evidence(self, request: CreateEvidenceRequest) -> Evidence:
        """创建证据记录"""
        evidence = Evidence(
            id=f"ev_{uuid.uuid4().hex}",
            session_id=request.session_id,
            plan_id=request.plan_id,
            step_id=request.step_id,
            type=request.type,
            source=request.source,
            content=request.content,
            summary=request.summary,
            confidence=request.confidence,
            metadata=request.metadata,
        )
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO evidence (id, session_id, plan_id, step_id, type, source, content, summary, confidence, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            evidence.id,
            evidence.session_id,
            evidence.plan_id,
            evidence.step_id,
            evidence.type.value,
            evidence.source,
            evidence.content,
            evidence.summary,
            evidence.confidence.value,
            json.dumps(evidence.metadata, ensure_ascii=False),
            evidence.created_at.isoformat(),
        ))
        conn.commit()
        conn.close()
        return evidence

    def list_evidence(self, session_id: str) -> List[Evidence]:
        """列出会话证据"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM evidence WHERE session_id = ? ORDER BY created_at", (session_id,))
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_evidence(row) for row in rows]

    def create_pending_input(self, pending: PendingInput) -> PendingInput:
        """创建待用户输入记录"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO pending_inputs (
                id, session_id, plan_id, step_id, input_type, question, reason, options_json,
                recommended_value, status, metadata_json, created_at, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pending.id,
            pending.session_id,
            pending.plan_id,
            pending.step_id,
            pending.input_type,
            pending.question,
            pending.reason,
            json.dumps([option.model_dump() for option in pending.options], ensure_ascii=False),
            pending.recommended_value,
            pending.status,
            json.dumps(pending.metadata, ensure_ascii=False),
            pending.created_at.isoformat(),
            pending.resolved_at.isoformat() if pending.resolved_at else None,
        ))
        conn.commit()
        conn.close()
        return pending

    def get_active_pending_input(self, session_id: str) -> Optional[PendingInput]:
        """获取会话中未解决的用户输入请求"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM pending_inputs
            WHERE session_id = ? AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT 1
        """, (session_id,))
        row = cursor.fetchone()
        conn.close()
        return self._row_to_pending_input(row) if row else None

    def resolve_pending_input(self, pending_input_id: str) -> None:
        """标记待输入为已解决"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE pending_inputs
            SET status = 'resolved', resolved_at = ?
            WHERE id = ?
        """, (datetime.utcnow().isoformat(), pending_input_id))
        conn.commit()
        conn.close()

    def create_report(
        self,
        session_id: str,
        content: str,
        evidence_ids: List[str],
        report_format: str = "markdown",
        metadata: Optional[Dict[str, Any]] = None,
        plan_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建报告记录"""
        report = {
            "id": f"rep_{uuid.uuid4().hex}",
            "session_id": session_id,
            "plan_id": plan_id,
            "format": report_format,
            "content": content,
            "evidence_ids": evidence_ids,
            "metadata": metadata or {},
            "created_at": datetime.utcnow(),
        }
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO reports (id, session_id, plan_id, format, content, evidence_ids_json, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report["id"],
            session_id,
            plan_id,
            report_format,
            content,
            json.dumps(evidence_ids, ensure_ascii=False),
            json.dumps(report["metadata"], ensure_ascii=False),
            report["created_at"].isoformat(),
        ))
        conn.commit()
        conn.close()
        return {**report, "created_at": report["created_at"].isoformat()}

    def get_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        """获取报告"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "plan_id": row["plan_id"] if "plan_id" in row.keys() else None,
            "format": row["format"],
            "content": row["content"],
            "evidence_ids": json.loads(row["evidence_ids_json"] or "[]"),
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"],
        }

    def list_reports(self, session_id: str) -> List[Dict[str, Any]]:
        """列出会话报告"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reports WHERE session_id = ? ORDER BY created_at DESC", (session_id,))
        rows = cursor.fetchall()
        conn.close()
        return [{
            "id": row["id"],
            "session_id": row["session_id"],
            "plan_id": row["plan_id"] if "plan_id" in row.keys() else None,
            "format": row["format"],
            "content": row["content"],
            "evidence_ids": json.loads(row["evidence_ids_json"] or "[]"),
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"],
        } for row in rows]

    def save_feedback(
        self,
        session_id: str,
        report_id: Optional[str],
        adopted: Optional[bool],
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """保存用户反馈"""
        feedback = {
            "id": f"fb_{uuid.uuid4().hex}",
            "session_id": session_id,
            "report_id": report_id,
            "adopted": adopted,
            "comment": comment,
            "created_at": datetime.utcnow().isoformat(),
        }
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO feedback (id, session_id, report_id, adopted, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            feedback["id"],
            session_id,
            report_id,
            None if adopted is None else int(adopted),
            comment,
            feedback["created_at"],
        ))
        conn.commit()
        conn.close()
        return feedback

    def _upsert_execution_step(self, cursor: sqlite3.Cursor, step: ExecutionStep) -> None:
        cursor.execute("""
            INSERT OR REPLACE INTO execution_steps (
                id, plan_id, session_id, type, name, status, input_json, output_json,
                evidence_ids_json, error_json, metadata_json, started_at, completed_at,
                elapsed_ms, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            step.id,
            step.plan_id,
            step.session_id,
            step.type.value,
            step.name,
            step.status.value,
            json.dumps(step.input, ensure_ascii=False),
            json.dumps(step.output, ensure_ascii=False) if step.output is not None else None,
            json.dumps(step.evidence_ids, ensure_ascii=False),
            json.dumps(step.error, ensure_ascii=False) if step.error is not None else None,
            json.dumps(step.metadata, ensure_ascii=False),
            step.started_at.isoformat() if step.started_at else None,
            step.completed_at.isoformat() if step.completed_at else None,
            step.elapsed_ms,
            step.created_at.isoformat(),
            step.updated_at.isoformat(),
        ))

    def _list_execution_steps_with_cursor(self, cursor: sqlite3.Cursor, plan_id: str) -> List[ExecutionStep]:
        cursor.execute("""
            SELECT * FROM execution_steps
            WHERE plan_id = ?
            ORDER BY created_at
        """, (plan_id,))
        return [self._row_to_execution_step(row) for row in cursor.fetchall()]

    def _row_to_execution_plan(self, row: sqlite3.Row) -> ExecutionPlan:
        return ExecutionPlan(
            id=row["id"],
            session_id=row["session_id"],
            user_message_id=row["user_message_id"],
            intent=row["intent"],
            status=ExecutionPlanStatus(row["status"]),
            goal=row["goal"] or "",
            current_step_id=row["current_step_id"],
            evidence_ids=json.loads(row["evidence_ids_json"] or "[]"),
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_execution_step(self, row: sqlite3.Row) -> ExecutionStep:
        return ExecutionStep(
            id=row["id"],
            plan_id=row["plan_id"],
            session_id=row["session_id"],
            type=ExecutionStepType(row["type"]),
            name=row["name"],
            status=ExecutionStepStatus(row["status"]),
            input=json.loads(row["input_json"] or "{}"),
            output=json.loads(row["output_json"]) if row["output_json"] else None,
            evidence_ids=json.loads(row["evidence_ids_json"] or "[]"),
            error=json.loads(row["error_json"]) if row["error_json"] else None,
            metadata=json.loads(row["metadata_json"] or "{}"),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            elapsed_ms=row["elapsed_ms"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_evidence(self, row: sqlite3.Row) -> Evidence:
        return Evidence(
            id=row["id"],
            session_id=row["session_id"],
            plan_id=row["plan_id"] if "plan_id" in row.keys() else None,
            step_id=row["step_id"] if "step_id" in row.keys() else None,
            type=EvidenceType(row["type"]),
            source=row["source"],
            content=row["content"],
            summary=row["summary"],
            confidence=EvidenceConfidence(row["confidence"] or "unknown"),
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_diagnosis_context(self, row: sqlite3.Row) -> "DiagnosisContext":
        _, DiagnosisContext, _, _ = _diagnosis_models()
        return DiagnosisContext.model_validate(json.loads(row["context_json"]))

    def _row_to_diagnosis_operation(self, row: sqlite3.Row) -> "DiagnosisOperation":
        _, _, DiagnosisOperation, OperationStatus = _diagnosis_models()
        return DiagnosisOperation(
            operation_id=row["operation_id"],
            session_id=row["session_id"],
            diagnosis_id=row["diagnosis_id"],
            idempotency_key=row["idempotency_key"],
            type=row["type"],
            status=OperationStatus(row["status"]),
            payload=json.loads(row["payload_json"] or "{}"),
            target_pending_id=row["target_pending_id"],
            expected_revision=row["expected_revision"],
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            error=row["error"] if "error" in row.keys() else None,
        )

    def _row_to_diagnosis_audit_event(self, row: sqlite3.Row) -> "DiagnosisAuditEvent":
        DiagnosisAuditEvent, _, _, _ = _diagnosis_models()
        return DiagnosisAuditEvent(
            id=row["id"],
            session_id=row["session_id"],
            diagnosis_id=row["diagnosis_id"],
            event_type=row["event_type"],
            revision=row["revision"],
            payload=json.loads(row["payload_json"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_pending_input(self, row: sqlite3.Row) -> PendingInput:
        options = [PendingInputOption(**item) for item in json.loads(row["options_json"] or "[]")]
        return PendingInput(
            id=row["id"],
            session_id=row["session_id"],
            plan_id=row["plan_id"] if "plan_id" in row.keys() else None,
            step_id=row["step_id"] if "step_id" in row.keys() else None,
            input_type=row["input_type"],
            question=row["question"],
            reason=row["reason"] or "",
            options=options,
            recommended_value=row["recommended_value"],
            status=row["status"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
            resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
        )

    def _enum_value(self, value: Any) -> Any:
        return getattr(value, "value", value)

    def _context_to_dict(self, context: AnalysisContext) -> dict:
        """上下文转字典"""
        return {
            "data_path": context.data_path,
            "data_id": context.data_id,
            "data_type": context.data_type,
            "problem_type": context.problem_type,
            "analysis_results": context.analysis_results
        }

    def _dict_to_context(self, data: dict) -> AnalysisContext:
        """字典转上下文"""
        return AnalysisContext(
            data_path=data.get("data_path"),
            data_id=data.get("data_id"),
            data_type=data.get("data_type"),
            problem_type=data.get("problem_type"),
            analysis_results=data.get("analysis_results", {})
        )
