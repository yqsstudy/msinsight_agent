"""会话存储 - 基于SQLite的会话持久化"""

import json
import sqlite3
from datetime import datetime
from typing import List, Optional
import os

from ..models import Session, Message, AnalysisContext


class SessionStore:
    """会话存储"""

    def __init__(self, storage_path: str = "./sessions"):
        self.storage_path = storage_path
        self.db_path = os.path.join(storage_path, "sessions.db")
        self._ensure_storage()

    def _ensure_storage(self):
        """确保存储目录和数据库存在"""
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

        conn.commit()
        conn.close()

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
