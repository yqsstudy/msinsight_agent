"""Policy for automatic MCP step execution."""

import fnmatch
import uuid
from typing import Optional

from ..models.config import OrchestratorConfig
from ..models.orchestration import AutoExecutionDecision, MCPToolResult, PendingInput


class InteractionPolicy:
    """Decides whether the orchestrator can continue without user input."""

    def __init__(self, config: Optional[OrchestratorConfig] = None):
        self.config = config or OrchestratorConfig()

    def decide_after_mcp_result(
        self,
        session_id: str,
        result: MCPToolResult,
        auto_step_count: int,
    ) -> AutoExecutionDecision:
        if result.error:
            pending = PendingInput(
                id=f"pin_{uuid.uuid4().hex}",
                session_id=session_id,
                input_type="text",
                question="MCP 工具执行失败，请检查输入或服务状态后补充说明。",
                reason=result.error,
                metadata={"resume_action": "retry_or_stop", "tool_name": result.tool_name},
            )
            return AutoExecutionDecision(action="require_user_input", reason="MCP 工具返回错误", pending_input=pending)

        if result.requires_user_input:
            pending = PendingInput(
                id=f"pin_{uuid.uuid4().hex}",
                session_id=session_id,
                input_type="text",
                question="MCP 返回需要补充信息，请根据提示提供参数或选择。",
                reason=result.text[:1000],
                metadata={"resume_action": "continue_mcp", "tool_name": result.tool_name},
            )
            return AutoExecutionDecision(action="require_user_input", reason="MCP 需要用户补充信息", pending_input=pending)

        if not result.next_step or not result.next_step.tool_name:
            return AutoExecutionDecision(action="stop_and_summarize", reason="MCP 未返回可自动执行的下一步")

        next_tool = result.next_step.tool_name
        if self._is_side_effect_tool(next_tool):
            pending = PendingInput(
                id=f"pin_{uuid.uuid4().hex}",
                session_id=session_id,
                input_type="confirm",
                question=f"下一步工具 `{next_tool}` 可能产生副作用，是否继续执行？",
                reason="该工具命中副作用工具模式，需要用户确认。",
                recommended_value="false",
                metadata={"resume_action": "execute_next_tool", "tool_name": next_tool},
            )
            return AutoExecutionDecision(action="require_user_input", reason="下一步可能产生副作用", pending_input=pending)

        if auto_step_count >= self.config.max_auto_steps:
            return AutoExecutionDecision(action="stop_and_summarize", reason="达到自动执行最大步数")

        if not self.config.auto_execute:
            pending = PendingInput(
                id=f"pin_{uuid.uuid4().hex}",
                session_id=session_id,
                input_type="confirm",
                question=f"是否继续执行下一步 `{next_tool}`？",
                reason="自动执行已关闭。",
                recommended_value="true",
                metadata={"resume_action": "execute_next_tool", "tool_name": next_tool},
            )
            return AutoExecutionDecision(action="require_user_input", reason="自动执行关闭", pending_input=pending)

        return AutoExecutionDecision(action="continue_auto", reason="下一步为只读且参数可由编排器解析")

    def allow_llm_assistance(self, stage: str) -> bool:
        return stage in {
            "query_rewrite",
            "candidate_recommendation",
            "parameter_extraction",
            "summary_enhancement",
        }

    def _is_side_effect_tool(self, tool_name: str) -> bool:
        if not self.config.require_confirmation_for_side_effects:
            return False
        return any(fnmatch.fnmatch(tool_name, pattern) for pattern in self.config.side_effect_tool_patterns)
