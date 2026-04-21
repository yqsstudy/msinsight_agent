"""集成测试 - Agent控制器"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from src.core.agent_controller import AgentController
from src.core.state_machine import State
from src.models import Session


class TestAgentController:

    def setup_method(self):
        """设置测试环境"""
        self.controller = AgentController()

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
        with patch.object(self.controller.llm_router, 'chat', new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = {"content": "这是一个测试回答"}

            result = await self.controller.process_message(
                message="什么是慢卡分析？",
                session_id=session.id
            )

            assert "response" in result
            assert result["state"] in [s.value for s in State]

    @pytest.mark.asyncio
    async def test_full_analysis_flow(self):
        """测试全量分析流程"""
        session = self.controller.create_session()

        # Mock MCP工具调用
        with patch.object(self.controller.mcp_client, 'call_tool', new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {
                "data_id": "test_data",
                "data_type": "profiling",
                "summary": {"total_ranks": 8}
            }

            result = await self.controller.process_message(
                message="帮我分析 /path/to/test/data",
                session_id=session.id
            )

            assert "response" in result
            assert "state" in result

    @pytest.mark.asyncio
    async def test_targeted_analysis(self):
        """测试定向分析"""
        session = self.controller.create_session()

        with patch.object(self.controller.mcp_client, 'call_tool', new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {
                "issues": [{"type": "oom", "severity": "high"}],
                "metrics": {"peak_memory": "90%"}
            }

            result = await self.controller.process_message(
                message="分析 /path/to/data 的内存问题",
                session_id=session.id
            )

            assert "response" in result

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

        with patch.object(self.controller.mcp_client, 'call_tool', new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {
                "slow_cards": [{"rank": 3, "latency": 250}],
                "analysis": {}
            }

            result = await self.controller.process_message(
                message="1",
                session_id=session.id
            )

            assert "response" in result
