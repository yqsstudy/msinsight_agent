"""对话管理器 - 管理用户对话上下文和多轮交互"""

import uuid
from datetime import datetime
from typing import Optional, List

from ..models import Session, Message, AnalysisContext, Option
from ..storage import SessionStore


class DialogManager:
    """管理用户对话上下文和多轮交互"""

    def __init__(self, session_store: SessionStore):
        self.session_store = session_store
        self.current_session: Optional[Session] = None

    def start_session(self, user_id: str = "default") -> Session:
        """创建新会话"""
        session = Session(
            id=str(uuid.uuid4()),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            messages=[],
            state="IDLE",
            context=AnalysisContext()
        )
        self.session_store.save(session)
        self.current_session = session
        return session

    def resume_session(self, session_id: str) -> Optional[Session]:
        """恢复历史会话"""
        session = self.session_store.load(session_id)
        if session:
            self.current_session = session
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        return self.session_store.load(session_id)

    def list_sessions(self, limit: int = 20) -> List[Session]:
        """获取会话列表"""
        return self.session_store.list_all(limit)

    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        return self.session_store.delete(session_id)

    def add_message(self, role: str, content: str, metadata: dict = None) -> Message:
        """添加消息到当前会话"""
        if not self.current_session:
            raise ValueError("No active session")

        message = Message(
            id=str(uuid.uuid4()),
            role=role,
            content=content,
            timestamp=datetime.now(),
            metadata=metadata or {}
        )
        self.current_session.messages.append(message)
        self.current_session.updated_at = datetime.now()
        self.session_store.save(self.current_session)
        return message

    def update_state(self, new_state: str):
        """更新会话状态"""
        if self.current_session:
            self.current_session.state = new_state
            self.current_session.updated_at = datetime.now()
            self.session_store.save(self.current_session)

    def update_context(self, **kwargs):
        """更新分析上下文"""
        if self.current_session:
            for key, value in kwargs.items():
                if hasattr(self.current_session.context, key):
                    setattr(self.current_session.context, key, value)
            self.current_session.updated_at = datetime.now()
            self.session_store.save(self.current_session)

    def set_pending_choices(self, question: str, options: List[Option], reason: str):
        """设置待用户选择的选项"""
        if self.current_session:
            self.current_session.context.pending_choices = options
            self.update_state("WAITING_INPUT")
            # 存储问题和原因到上下文
            self.current_session.context.analysis_results["_pending_question"] = question
            self.current_session.context.analysis_results["_pending_reason"] = reason
            self.session_store.save(self.current_session)

    def clear_pending_choices(self):
        """清除待选择项"""
        if self.current_session:
            self.current_session.context.pending_choices = None
            self.current_session.context.analysis_results.pop("_pending_question", None)
            self.current_session.context.analysis_results.pop("_pending_reason", None)
            self.session_store.save(self.current_session)

    def get_pending_info(self) -> tuple:
        """获取待选择信息"""
        if not self.current_session:
            return None, [], None
        ctx = self.current_session.context
        question = ctx.analysis_results.get("_pending_question", "")
        reason = ctx.analysis_results.get("_pending_reason", "")
        return question, ctx.pending_choices or [], reason
