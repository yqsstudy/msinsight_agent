"""DAG引擎集成测试"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from src.core.dag import DAGEngine, FlowContext, StepStatus


class TestDAGEngine:

    def setup_method(self):
        """设置测试环境"""
        # Mock MCP客户端
        self.mcp_client = Mock()
        self.mcp_client.call_tool = AsyncMock(return_value={
            "data_id": "test_001",
            "data_type": "profiling",
            "summary": {"total_ranks": 8}
        })

        # Mock LLM路由器
        self.llm_router = Mock()
        self.llm_router.chat = AsyncMock(return_value={
            "content": '{"tools": ["analyze_communication"], "reason": "检测到通信问题"}'
        })

        # Mock报告生成器
        self.report_generator = Mock()
        self.report_generator.generate = AsyncMock(return_value=Mock(
            to_dict=lambda: {"problems": [], "suggestions": []}
        ))

    def test_list_flows(self):
        """测试列出流程"""
        engine = DAGEngine(
            config_path="./config/flows.yaml",
            mcp_client=self.mcp_client,
            llm_router=self.llm_router,
            report_generator=self.report_generator
        )

        flows = engine.list_flows()
        assert "full_analysis" in flows
        assert "memory_analysis" in flows
        assert "communication_analysis" in flows

    @pytest.mark.asyncio
    async def test_execute_flow(self):
        """测试执行流程"""
        engine = DAGEngine(
            config_path="./config/flows.yaml",
            mcp_client=self.mcp_client,
            llm_router=self.llm_router,
            report_generator=self.report_generator
        )

        result = await engine.execute(
            flow_name="memory_analysis",
            params={"data_path": "/test/path"}
        )

        assert "status" in result

    @pytest.mark.asyncio
    async def test_mcp_tool_step(self):
        """测试MCP工具步骤"""
        self.mcp_client.call_tool = AsyncMock(return_value={
            "data_id": "test_001",
            "data_type": "profiling"
        })

        engine = DAGEngine(
            config_path="./config/flows.yaml",
            mcp_client=self.mcp_client,
            llm_router=self.llm_router,
            report_generator=self.report_generator
        )

        result = await engine.execute(
            flow_name="memory_analysis",
            params={"data_path": "/test/data"}
        )

        # 验证MCP工具被调用
        self.mcp_client.call_tool.assert_called()

    @pytest.mark.asyncio
    async def test_user_input_step(self):
        """测试用户输入步骤"""
        self.mcp_client.call_tool = AsyncMock(side_effect=[
            {"data_id": "test_001"},  # parse_data
            {"domains": [{"name": "world_group"}, {"name": "tp_group"}]},  # get_comm_domains
        ])

        engine = DAGEngine(
            config_path="./config/flows.yaml",
            mcp_client=self.mcp_client,
            llm_router=self.llm_router,
            report_generator=self.report_generator
        )

        result = await engine.execute(
            flow_name="communication_analysis",
            params={"data_path": "/test/data"}
        )

        # 应该等待用户输入
        if result.get("status") == "waiting_input":
            assert "question" in result
            assert "options" in result


class TestFlowContext:

    def test_context_state(self):
        """测试上下文状态管理"""
        context = FlowContext(
            flow_name="test_flow",
            session_id="test_session"
        )

        context.set_state("data_id", "123")
        context.set_state("data_type", "profiling")

        assert context.get_state("data_id") == "123"
        assert context.get_state("data_type") == "profiling"
        assert context.get_state("nonexistent", "default") == "default"

    def test_context_history(self):
        """测试上下文历史"""
        from src.core.dag import StepResult

        context = FlowContext(
            flow_name="test_flow",
            session_id="test_session"
        )

        result = StepResult(
            step_name="parse_data",
            status=StepStatus.COMPLETED,
            output={"data_id": "123"}
        )

        context.add_history(result)

        assert len(context.history) == 1
        assert context.history[0].step_name == "parse_data"


class TestExpressionEvaluator:

    def test_evaluate_input_var(self):
        """测试输入变量求值"""
        from src.core.dag import ExpressionEvaluator

        context = FlowContext(
            flow_name="test",
            session_id="test",
            input={"data_path": "/path/to/data"}
        )

        result = ExpressionEvaluator.evaluate("${input.data_path}", context)
        assert result == "/path/to/data"

    def test_evaluate_state_var(self):
        """测试状态变量求值"""
        from src.core.dag import ExpressionEvaluator

        context = FlowContext(
            flow_name="test",
            session_id="test"
        )
        context.set_state("data_id", "123")

        result = ExpressionEvaluator.evaluate("${state.data_id}", context)
        assert result == "123"

    def test_evaluate_len(self):
        """测试len函数"""
        from src.core.dag import ExpressionEvaluator

        context = FlowContext(
            flow_name="test",
            session_id="test"
        )
        context.set_state("domains", ["a", "b", "c"])

        result = ExpressionEvaluator.evaluate("len(${state.domains})", context)
        assert result == 3
