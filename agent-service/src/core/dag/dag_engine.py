"""DAG引擎主类"""

import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable
import uuid
import time

from .engine import (
    DAGConfig, FlowContext, StepResult, StepStatus, StepType,
    ExpressionEvaluator
)
from .executors import (
    BaseStepExecutor, MCPToolExecutor, InternalHandlerExecutor,
    DecisionExecutor, ConditionExecutor, ParallelExecutor,
    UserInputExecutor, ReportExecutor
)
from ...observability import (
    record_dag_flow,
    record_dag_step,
    get_logger,
)

logger = get_logger(__name__)


class DAGEngine:
    """DAG工作流引擎"""

    def __init__(
        self,
        config_path: str = "./config/flows.yaml",
        mcp_client=None,
        llm_router=None,
        report_generator=None
    ):
        self.config = DAGConfig(config_path)
        self.mcp_client = mcp_client
        self.llm_router = llm_router
        self.report_generator = report_generator

        # 初始化执行器
        self._init_executors()

        # 运行中的上下文
        self._contexts: Dict[str, FlowContext] = {}

    def _init_executors(self):
        """初始化步骤执行器"""
        self.executors: Dict[str, BaseStepExecutor] = {
            StepType.MCP_TOOL.value: MCPToolExecutor(self.mcp_client),
            StepType.INTERNAL.value: InternalHandlerExecutor(),
            StepType.DECISION.value: DecisionExecutor(self.llm_router),
            StepType.CONDITION.value: ConditionExecutor(),
            StepType.USER_INPUT.value: UserInputExecutor(),
        }

        # 并行执行器需要引用其他执行器
        self.executors[StepType.PARALLEL.value] = ParallelExecutor(self.executors)

        # 报告执行器
        self.executors[StepType.REPORT.value] = ReportExecutor(
            self.report_generator, self.llm_router
        )

    def register_handler(self, name: str, handler: Callable):
        """注册内部处理器"""
        executor = self.executors.get(StepType.INTERNAL.value)
        if isinstance(executor, InternalHandlerExecutor):
            executor.register_handler(name, handler)

    async def execute(
        self,
        flow_name: str,
        params: Dict[str, Any],
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        执行流程

        Args:
            flow_name: 流程名称
            params: 输入参数
            session_id: 会话ID（可选，用于恢复）

        Returns:
            执行结果
        """
        start_time = time.time()
        status = "success"

        try:
            # 获取流程定义
            flow_config = self.config.get_flow(flow_name)
            if not flow_config:
                raise ValueError(f"Flow not found: {flow_name}")

            # 创建或恢复上下文
            if session_id and session_id in self._contexts:
                context = self._contexts[session_id]
            else:
                session_id = session_id or str(uuid.uuid4())
                context = FlowContext(
                    flow_name=flow_name,
                    session_id=session_id,
                    input=params
                )
                self._contexts[session_id] = context

            # 获取入口点
            entry_point = flow_config.get("entry_point")
            steps = flow_config.get("steps", {})

            if not entry_point or entry_point not in steps:
                raise ValueError(f"Invalid entry point: {entry_point}")

            # 执行流程
            context.status = "running"
            context.current_step = entry_point

            logger.info(f"Starting flow execution: {flow_name}, session: {session_id}")

            try:
                result = await self._execute_flow(steps, context, entry_point)
                context.status = "completed"
                logger.info(f"Flow completed: {flow_name}, session: {session_id}")
                return result

            except Exception as e:
                context.status = "failed"
                status = "error"
                logger.error(f"Flow failed: {flow_name}, session: {session_id}, error: {e}")
                return {
                    "status": "error",
                    "error": str(e),
                    "context": context.to_dict()
                }

        finally:
            duration = time.time() - start_time
            record_dag_flow(flow_name, status, duration)

    async def _execute_flow(
        self,
        steps: Dict[str, Any],
        context: FlowContext,
        current_step: str
    ) -> Dict[str, Any]:
        """执行流程步骤"""
        while current_step and current_step != "END":
            step_config = steps.get(current_step)
            if not step_config:
                break

            context.current_step = current_step

            # 执行步骤
            result = await self._execute_step(step_config, context)
            context.add_history(result)

            # 更新状态
            for key, value in result.output.items():
                context.set_state(key, value)

            # 检查是否需要用户输入
            if result.status == StepStatus.WAITING_INPUT:
                return {
                    "status": "waiting_input",
                    "question": result.question,
                    "options": result.options,
                    "reason": result.reason,
                    "context": context.to_dict()
                }

            # 检查是否失败
            if result.status == StepStatus.FAILED:
                return {
                    "status": "error",
                    "error": result.error,
                    "context": context.to_dict()
                }

            # 确定下一步
            current_step = self._get_next_step(step_config, result, context)

        # 流程完成
        return {
            "status": "completed",
            "output": context.state,
            "context": context.to_dict()
        }

    async def _execute_step(
        self,
        step_config: Dict[str, Any],
        context: FlowContext
    ) -> StepResult:
        """执行单个步骤"""
        step_type = step_config.get("type", "mcp_tool")
        step_name = context.current_step
        executor = self.executors.get(step_type)

        if not executor:
            record_dag_step(context.flow_name, step_name, step_type, "error")
            return StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                error=f"No executor for step type: {step_type}"
            )

        result = await executor.execute(step_config, context)
        step_status = "success" if result.status == StepStatus.COMPLETED else "error"
        record_dag_step(context.flow_name, step_name, step_type, step_status)

        return result

    def _get_next_step(
        self,
        step_config: Dict[str, Any],
        result: StepResult,
        context: FlowContext
    ) -> Optional[str]:
        """确定下一步"""
        # 检查是否有条件分支
        if "next" in step_config:
            next_config = step_config["next"]

            if isinstance(next_config, str):
                return next_config

            if isinstance(next_config, dict):
                # 条件步骤的结果决定下一步
                matched_rule = result.output.get("matched_rule")
                if matched_rule:
                    return result.output.get("next_step")

        return None

    async def continue_with_input(
        self,
        session_id: str,
        user_input: Any
    ) -> Dict[str, Any]:
        """
        用户输入后继续执行

        Args:
            session_id: 会话ID
            user_input: 用户输入（选择的值或文本）

        Returns:
            执行结果
        """
        context = self._contexts.get(session_id)
        if not context:
            raise ValueError(f"Session not found: {session_id}")

        # 获取流程定义
        flow_config = self.config.get_flow(context.flow_name)
        steps = flow_config.get("steps", {})

        # 更新用户输入到状态
        if isinstance(user_input, dict):
            for key, value in user_input.items():
                context.set_state(key, value)
        else:
            context.set_state("user_input", user_input)
            context.set_state("selected_domain", user_input)

        # 获取当前步骤配置，找到下一步
        current_step_config = steps.get(context.current_step)
        if not current_step_config:
            raise ValueError(f"Current step not found: {context.current_step}")

        # 确定下一步
        next_step = current_step_config.get("next")
        if isinstance(next_step, dict):
            # 根据当前步骤名称映射
            next_step = next_step.get(context.current_step)

        if not next_step or next_step == "END":
            return {
                "status": "completed",
                "output": context.state,
                "context": context.to_dict()
            }

        # 继续执行
        context.status = "running"
        try:
            result = await self._execute_flow(steps, context, next_step)
            context.status = "completed"
            return result

        except Exception as e:
            context.status = "failed"
            return {
                "status": "error",
                "error": str(e),
                "context": context.to_dict()
            }

    def get_context(self, session_id: str) -> Optional[FlowContext]:
        """获取上下文"""
        return self._contexts.get(session_id)

    def list_flows(self) -> List[str]:
        """列出所有流程"""
        return self.config.list_flows()

    def reload_config(self):
        """重新加载配置"""
        self.config.reload()
