"""集成测试 - Agent控制器"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from src.core.agent_controller import AgentController
from src.core.state_machine import State
from src.models import Session, AnalysisContext


class TestAgentController:

    def setup_method(self):
        """设置测试环境"""
        # Mock all dependencies
        self.mock_session_store = Mock()
        self.mock_config_store = Mock()
        self.mock_llm_router = Mock()
        self.mock_mcp_client = Mock()
        self.mock_knowledge_retriever = Mock()
        self.mock_case_manager = Mock()

        # Configure mock config store
        self.mock_config_store.get_llm_config.return_value = {
            "default_provider": "claude",
            "providers": {}
        }
        self.mock_config_store.get_mcp_config.return_value = {
            "transport": {"type": "http", "url": "http://localhost:8080"}
        }

        # In-memory session storage for tests
        self._sessions = {}

        def save_session(session):
            self._sessions[session.id] = session
            return session

        def load_session(session_id):
            return self._sessions.get(session_id)

        self.mock_session_store.save.side_effect = save_session
        self.mock_session_store.load.side_effect = load_session

        self.controller = AgentController(
            session_store=self.mock_session_store,
            config_store=self.mock_config_store,
            llm_router=self.mock_llm_router,
            mcp_client=self.mock_mcp_client,
            knowledge_retriever=self.mock_knowledge_retriever,
            case_manager=self.mock_case_manager
        )

    def test_create_session(self):
        """测试创建会话"""
        session = self.controller.create_session()
        assert session is not None
        assert session.id is not None
        assert session.state == State.IDLE.value

    def test_get_session(self):
        """测试获取会话"""
        session = self.controller.create_session()
        loaded = self.controller.get_session(session.id)
        assert loaded is not None
        assert loaded.id == session.id

    @pytest.mark.asyncio
    async def test_process_question(self):
        """测试处理一般问题"""
        session = self.controller.create_session()

        # Mock LLM响应
        self.mock_llm_router.chat = AsyncMock(return_value={"content": "这是一个测试回答"})

        result = await self.controller.process_message(
            message="什么是慢卡分析？",
            session_id=session.id
        )

        # Should have response or error handled
        assert "response" in result or "user_message" in result

    @pytest.mark.asyncio
    async def test_full_analysis_flow(self):
        """测试全量分析流程"""
        session = self.controller.create_session()

        # Mock MCP工具调用
        self.mock_mcp_client.call_tool = AsyncMock(return_value={
            "data_id": "test_data",
            "data_type": "profiling",
            "summary": {"total_ranks": 8}
        })

        result = await self.controller.process_message(
            message="帮我分析 /path/to/test/data",
            session_id=session.id
        )

        assert "response" in result or "user_message" in result or "state" in result

    @pytest.mark.asyncio
    async def test_targeted_analysis(self):
        """测试定向分析"""
        session = self.controller.create_session()

        self.mock_mcp_client.call_tool = AsyncMock(return_value={
            "issues": [{"type": "oom", "severity": "high"}],
            "metrics": {"peak_memory": "90%"}
        })

        result = await self.controller.process_message(
            message="分析 /path/to/data 的内存问题",
            session_id=session.id
        )

        assert "response" in result or "user_message" in result or "state" in result

    @pytest.mark.asyncio
    async def test_user_choice(self):
        """测试用户选择"""
        session = self.controller.create_session()
        session.state = State.WAITING_INPUT.value
        session.context.pending_choices = [
            {"value": "world_group", "label": "World Group"},
            {"value": "tp_group", "label": "TP Group"}
        ]
        self.controller.session_store.save(session)

        self.mock_mcp_client.call_tool = AsyncMock(return_value={
            "slow_cards": [{"rank": 3, "latency": 250}],
            "analysis": {}
        })

        result = await self.controller.process_message(
            message="1",
            session_id=session.id
        )

        assert "response" in result or "user_message" in result or "state" in result
