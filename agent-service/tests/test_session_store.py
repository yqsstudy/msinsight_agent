"""测试会话存储"""

import pytest
import tempfile
import os
from datetime import datetime

from src.storage.session_store import SessionStore
from src.models import Session, Message, AnalysisContext


class TestSessionStore:

    def setup_method(self):
        # 使用临时目录
        self.temp_dir = tempfile.mkdtemp()
        self.store = SessionStore(self.temp_dir)

    def test_save_and_load_session(self):
        """测试保存和加载会话"""
        session = Session(
            id="test-session-1",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            state="IDLE"
        )
        self.store.save(session)

        loaded = self.store.load("test-session-1")
        assert loaded is not None
        assert loaded.id == "test-session-1"
        assert loaded.state == "IDLE"

    def test_save_session_with_messages(self):
        """测试保存带消息的会话"""
        session = Session(
            id="test-session-2",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            state="ANALYZING",
            messages=[
                Message(
                    id="msg-1",
                    role="user",
                    content="帮我分析数据",
                    timestamp=datetime.now()
                )
            ]
        )
        self.store.save(session)

        loaded = self.store.load("test-session-2")
        assert len(loaded.messages) == 1
        assert loaded.messages[0].content == "帮我分析数据"

    def test_list_sessions(self):
        """测试列出会话"""
        for i in range(3):
            session = Session(
                id=f"session-{i}",
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            self.store.save(session)

        sessions = self.store.list_all()
        assert len(sessions) == 3

    def test_delete_session(self):
        """测试删除会话"""
        session = Session(
            id="to-delete",
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        self.store.save(session)

        success = self.store.delete("to-delete")
        assert success

        loaded = self.store.load("to-delete")
        assert loaded is None

    def test_load_nonexistent_session(self):
        """测试加载不存在的会话"""
        loaded = self.store.load("nonexistent")
        assert loaded is None
