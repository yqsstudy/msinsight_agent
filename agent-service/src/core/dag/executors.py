"""步骤执行器 - 集成错误处理"""

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable
import re

from .engine import StepType, StepResult, StepStatus, FlowContext, ExpressionEvaluator
from ...error_handling import (
    RetryPolicy,
    RetryConfig,
    CircuitBreaker,
    CircuitConfig,
    ErrorHandler,
    ErrorContext,
    ErrorType,
    FallbackManager,
    circuit_registry,
    fallback_manager,
    error_handler,
)
from ...observability import get_logger

logger = get_logger(__name__)


class BaseStepExecutor(ABC):
    """步骤执行器基类"""

    @abstractmethod
    async def execute(
        self,
        step_config: Dict[str, Any],
        context: FlowContext
    ) -> StepResult:
        """执行步骤"""
        pass

    def resolve_params(self, params: Dict[str, Any], context: FlowContext) -> Dict[str, Any]:
        """解析参数中的表达式"""
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str) and value.startswith("${"):
                resolved[key] = ExpressionEvaluator.evaluate(value, context)
            elif isinstance(value, dict):
                resolved[key] = self.resolve_params(value, context)
            else:
                resolved[key] = value
        return resolved

    def extract_outputs(self, output: Any, output_config: Dict[str, str]) -> Dict[str, Any]:
        """提取输出"""
        result = {}
        for key, path in output_config.items():
            # 简单的JSONPath实现
            if path == "$":
                result[key] = output
            elif path.startswith("$."):
                keys = path[2:].split(".")
                value = output
                for k in keys:
                    if isinstance(value, dict):
                        value = value.get(k)
                    else:
                        value = None
                        break
                result[key] = value
        return result


class MCPToolExecutor(BaseStepExecutor):
    """MCP工具执行器 - 集成重试、熔断、降级"""

    def __init__(self, mcp_client):
        self.mcp_client = mcp_client

        # 初始化重试策略
        self.retry_policy = RetryPolicy(RetryConfig(
            max_attempts=3,
            base_delay=1.0,
            retryable_exceptions=(TimeoutError, ConnectionError)
        ))

        # 初始化熔断器
        self.circuit_breaker = circuit_registry.get_or_create(
            "mcp_tool",
            CircuitConfig(
                failure_threshold=5,
                timeout=30.0
            )
        )

    async def execute(
        self,
        step_config: Dict[str, Any],
        context: FlowContext
    ) -> StepResult:
        """执行MCP工具"""
        step_name = step_config.get("name", context.current_step)
        tool_name = step_name

        # 构建错误上下文
        error_ctx = ErrorContext(
            operation=f"mcp_tool_{tool_name}",
            session_id=context.session_id,
            flow_name=context.flow_name,
            step_name=step_name,
            tool_name=tool_name,
        )

        try:
            # 检查熔断器
            if not self.circuit_breaker.is_call_allowed():
                # 熔断器打开，执行降级
                logger.warning(f"Circuit breaker open, using fallback for tool: {tool_name}")
                fallback_result = await fallback_manager.execute_fallback(
                    f"mcp_tool_{tool_name}",
                    error=None
                )
                return StepResult(
                    step_name=step_name,
                    status=StepStatus.COMPLETED,
                    output=fallback_result or {}
                )

            # 解析参数
            params = self.resolve_params(
                step_config.get("params", {}),
                context
            )

            # 带重试的执行
            result = await self._execute_with_retry(tool_name, params, error_ctx)

            # 记录成功
            self.circuit_breaker.record_success()

            # 提取输出
            outputs = self.extract_outputs(result, step_config.get("outputs", {}))

            return StepResult(
                step_name=step_name,
                status=StepStatus.COMPLETED,
                output=outputs
            )

        except Exception as e:
            # 记录失败
            self.circuit_breaker.record_failure(e)

            # 处理错误
            handled = error_handler.handle(e, error_ctx)

            # 检查是否可以降级
            if handled.fallback_available:
                fallback_result = await fallback_manager.execute_fallback(
                    f"mcp_tool_{tool_name}",
                    error=e
                )
                if fallback_result is not None:
                    return StepResult(
                        step_name=step_name,
                        status=StepStatus.COMPLETED,
                        output=fallback_result
                    )

            return StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                error=handled.user_message,
                output={"error_type": handled.error_type.value}
            )

    async def _execute_with_retry(
        self,
        tool_name: str,
        params: Dict[str, Any],
        error_ctx: ErrorContext
    ) -> Dict[str, Any]:
        """带重试的执行"""
        attempt = 0
        max_attempts = 3
        last_error = None

        while attempt < max_attempts:
            attempt += 1
            error_ctx.attempt = attempt

            try:
                result = await self.mcp_client.call_tool(tool_name, params)
                return result

            except Exception as e:
                last_error = e
                handled = error_handler.handle(e, error_ctx)

                if not handled.recoverable or attempt >= max_attempts:
                    raise

                # 等待重试
                delay = error_handler.get_retry_delay(handled, attempt)
                logger.warning(
                    f"MCP tool call failed, retrying",
                    tool_name=tool_name,
                    attempt=attempt,
                    delay=delay
                )
                await asyncio.sleep(delay)

        raise last_error


class InternalHandlerExecutor(BaseStepExecutor):
    """内部处理器执行器"""

    def __init__(self, handlers: Dict[str, Callable] = None):
        self.handlers = handlers or {}

    def register_handler(self, name: str, handler: Callable):
        """注册处理器"""
        self.handlers[name] = handler

    async def execute(
        self,
        step_config: Dict[str, Any],
        context: FlowContext
    ) -> StepResult:
        """执行内部处理器"""
        step_name = step_config.get("name", context.current_step)
        handler_name = step_config.get("handler", step_name)

        try:
            handler = self.handlers.get(handler_name)
            if not handler:
                # 默认处理器
                return StepResult(
                    step_name=step_name,
                    status=StepStatus.COMPLETED,
                    output={}
                )

            # 执行处理器
            if asyncio.iscoroutinefunction(handler):
                result = await handler(context)
            else:
                result = handler(context)

            # 提取输出
            outputs = self.extract_outputs(result, step_config.get("outputs", {}))

            return StepResult(
                step_name=step_name,
                status=StepStatus.COMPLETED,
                output=outputs
            )

        except Exception as e:
            return StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                error=str(e)
            )


class DecisionExecutor(BaseStepExecutor):
    """决策执行器（LLM辅助）- 集成错误处理"""

    def __init__(self, llm_router):
        self.llm_router = llm_router

        # 初始化熔断器
        self.circuit_breaker = circuit_registry.get_or_create(
            "llm_decision",
            CircuitConfig(
                failure_threshold=3,
                timeout=20.0
            )
        )

    async def execute(
        self,
        step_config: Dict[str, Any],
        context: FlowContext
    ) -> StepResult:
        """执行LLM决策"""
        step_name = step_config.get("name", context.current_step)

        error_ctx = ErrorContext(
            operation="llm_decision",
            session_id=context.session_id,
            flow_name=context.flow_name,
            step_name=step_name,
        )

        try:
            # 检查熔断器
            if not self.circuit_breaker.is_call_allowed():
                logger.warning(f"LLM circuit breaker open, using fallback")
                # 降级：返回默认决策
                return StepResult(
                    step_name=step_name,
                    status=StepStatus.COMPLETED,
                    output={"tools": [], "reason": "LLM服务降级"}
                )

            # 构建prompt
            prompt_template = step_config.get("prompt_template", "")
            prompt = self._render_prompt(prompt_template, context)

            # 调用LLM
            response = await self.llm_router.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )

            content = response.get("content", "")

            # 解析JSON结果
            result = self._parse_json_response(content)

            # 记录成功
            self.circuit_breaker.record_success()

            # 提取输出
            outputs = self.extract_outputs(result, step_config.get("outputs", {}))

            return StepResult(
                step_name=step_name,
                status=StepStatus.COMPLETED,
                output=outputs
            )

        except Exception as e:
            self.circuit_breaker.record_failure(e)
            handled = error_handler.handle(e, error_ctx, ErrorType.LLM_ERROR)

            # LLM失败时返回空决策而非错误
            return StepResult(
                step_name=step_name,
                status=StepStatus.COMPLETED,
                output={"tools": [], "reason": handled.user_message}
            )

    def _render_prompt(self, template: str, context: FlowContext) -> str:
        """渲染prompt模板"""
        def replace_var(match):
            var_path = match.group(1)
            value = ExpressionEvaluator._resolve_path(var_path, context)
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return str(value) if value is not None else ""

        return re.sub(r'\$\{([^}]+)\}', replace_var, template)

    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        """解析JSON响应"""
        # 尝试提取JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return {}


class ConditionExecutor(BaseStepExecutor):
    """条件执行器"""

    async def execute(
        self,
        step_config: Dict[str, Any],
        context: FlowContext
    ) -> StepResult:
        """执行条件判断"""
        step_name = step_config.get("name", context.current_step)
        rules = step_config.get("rules", [])

        for rule in rules:
            condition = rule.get("condition", "")
            if ExpressionEvaluator.evaluate(condition, context):
                # 条件匹配
                next_step = rule.get("then")
                return StepResult(
                    step_name=step_name,
                    status=StepStatus.COMPLETED,
                    output={"matched_rule": rule.get("id"), "next_step": next_step}
                )

        # 无匹配条件
        return StepResult(
            step_name=step_name,
            status=StepStatus.COMPLETED,
            output={"matched_rule": None}
        )


class ParallelExecutor(BaseStepExecutor):
    """并行执行器"""

    def __init__(self, step_executors: Dict[str, BaseStepExecutor]):
        self.step_executors = step_executors

    async def execute(
        self,
        step_config: Dict[str, Any],
        context: FlowContext
    ) -> StepResult:
        """并行执行多个分支"""
        step_name = step_config.get("name", context.current_step)
        branches = step_config.get("branches", [])

        # 解析分支列表
        if isinstance(branches, str) and branches.startswith("${"):
            branches = ExpressionEvaluator.evaluate(branches, context) or []

        if not branches:
            return StepResult(
                step_name=step_name,
                status=StepStatus.COMPLETED,
                output={}
            )

        # 并行执行
        tasks = []
        for branch in branches:
            if isinstance(branch, str):
                # 工具名称
                task = self._execute_tool(branch, context)
            else:
                # 步骤配置
                task = self._execute_step(branch, context)
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 合并结果
        combined_output = {}
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                combined_output[f"branch_{i}_error"] = str(result)
            elif isinstance(result, StepResult):
                combined_output.update(result.output)

        return StepResult(
            step_name=step_name,
            status=StepStatus.COMPLETED,
            output=combined_output
        )

    async def _execute_tool(self, tool_name: str, context: FlowContext) -> StepResult:
        """执行单个工具"""
        executor = self.step_executors.get("mcp_tool")
        if executor:
            return await executor.execute(
                {"name": tool_name, "params": {"data_id": context.get_state("data_id")}},
                context
            )
        return StepResult(step_name=tool_name, status=StepStatus.FAILED, error="No executor")

    async def _execute_step(self, step_config: Dict, context: FlowContext) -> StepResult:
        """执行步骤"""
        step_type = step_config.get("type", "mcp_tool")
        executor = self.step_executors.get(step_type)
        if executor:
            return await executor.execute(step_config, context)
        return StepResult(step_name="unknown", status=StepStatus.FAILED, error="No executor")


class UserInputExecutor(BaseStepExecutor):
    """用户输入执行器"""

    async def execute(
        self,
        step_config: Dict[str, Any],
        context: FlowContext
    ) -> StepResult:
        """请求用户输入"""
        step_name = step_config.get("name", context.current_step)

        # 解析选项
        options_config = step_config.get("options", [])
        if isinstance(options_config, str) and options_config.startswith("${"):
            options_config = ExpressionEvaluator.evaluate(options_config, context) or []

        options = []
        for opt in options_config:
            if isinstance(opt, dict):
                options.append({
                    "value": opt.get("name", opt.get("value", "")),
                    "label": opt.get("name", opt.get("label", "")),
                    "description": opt.get("description", "")
                })
            elif isinstance(opt, str):
                options.append({"value": opt, "label": opt, "description": ""})

        return StepResult(
            step_name=step_name,
            status=StepStatus.WAITING_INPUT,
            need_input=True,
            question=step_config.get("question", "请选择："),
            options=options,
            reason=step_config.get("reason", ""),
            output={}
        )


class ReportExecutor(BaseStepExecutor):
    """报告生成执行器"""

    def __init__(self, report_generator, llm_router=None):
        self.report_generator = report_generator
        self.llm_router = llm_router

    async def execute(
        self,
        step_config: Dict[str, Any],
        context: FlowContext
    ) -> StepResult:
        """生成报告"""
        step_name = step_config.get("name", context.current_step)

        try:
            # 收集分析结果
            analysis_data = {
                "session_id": context.session_id,
                "data_id": context.get_state("data_id"),
                "data_type": context.get_state("data_type"),
                "problem_types": context.get_state("problem_types"),
                "analysis_results": {
                    "communication": context.get_state("slow_cards") or {},
                    "memory": context.get_state("issues") or {}
                }
            }

            # 生成报告
            report = await self.report_generator.generate(analysis_data)

            # LLM增强
            if step_config.get("enhance_by") == "llm" and self.llm_router:
                enhanced_summary = await self._enhance_report(report, context)
                report.summary = enhanced_summary

            return StepResult(
                step_name=step_name,
                status=StepStatus.COMPLETED,
                output={"report": report.to_dict()}
            )

        except Exception as e:
            return StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                error=str(e)
            )

    async def _enhance_report(self, report, context: FlowContext) -> str:
        """LLM增强报告"""
        prompt = f"""
        请基于以下分析结果，生成一份简洁的诊断报告摘要：

        问题列表: {report.problems}
        诊断结果: {report.diagnosis}
        优化建议: {report.suggestions}

        请用自然语言总结主要发现和建议，不超过200字。
        """

        response = await self.llm_router.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )

        return response.get("content", "")
