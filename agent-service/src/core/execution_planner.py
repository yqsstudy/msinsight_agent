"""Execution plan generation for Agent Harness requests."""

import uuid
from typing import Any, Dict, Optional

from ..models.orchestration import (
    ExecutionPlan,
    ExecutionStep,
    ExecutionStepType,
    IntentDecision,
    IntentType,
)


class ExecutionPlanner:
    """Builds auditable execution plans from intent decisions."""

    def create_plan(
        self,
        session_id: str,
        user_message_id: Optional[str],
        message: str,
        intent: IntentDecision,
    ) -> ExecutionPlan:
        plan_id = f"plan_{uuid.uuid4().hex}"
        plan = ExecutionPlan(
            id=plan_id,
            session_id=session_id,
            user_message_id=user_message_id,
            intent=intent.intent,
            goal=message,
            metadata={"reason": intent.reason, "confidence": intent.confidence, "extracted": intent.extracted},
        )
        plan.steps = self._build_steps(plan_id, session_id, message, intent)
        plan.current_step_id = plan.steps[0].id if plan.steps else None
        return plan

    def _build_steps(
        self,
        plan_id: str,
        session_id: str,
        message: str,
        intent: IntentDecision,
    ) -> list[ExecutionStep]:
        if intent.intent == IntentType.CHAT:
            return [self._step(plan_id, session_id, ExecutionStepType.CHAT_RESPONSE, "返回产品能力说明", {"message": message})]

        if intent.intent in {IntentType.KNOWLEDGE_QA, IntentType.KNOWLEDGE_RETRIEVE}:
            rag_type = ExecutionStepType.RAG_QA if intent.intent == IntentType.KNOWLEDGE_QA else ExecutionStepType.RAG_RETRIEVE
            return [
                self._step(plan_id, session_id, rag_type, "检索知识依据", {"query": message}),
                self._step(plan_id, session_id, ExecutionStepType.EVIDENCE_FUSION, "整理知识回答", {}),
                self._step(plan_id, session_id, ExecutionStepType.ANSWER_RESPONSE, "返回知识回答", {}),
            ]

        if intent.intent in {IntentType.DIAGNOSIS, IntentType.PROFILING_ANALYSIS}:
            return [
                self._step(plan_id, session_id, ExecutionStepType.MCP_SEARCH, "搜索 MCP profiling playbook", {"query": message}),
                self._step(plan_id, session_id, ExecutionStepType.USER_INPUT, "补齐路径、参数或 playbook 选择", {}, optional=True),
                self._step(plan_id, session_id, ExecutionStepType.MCP_EXECUTE, "执行 MCP profiling 工具", {"extracted": intent.extracted}),
                self._step(plan_id, session_id, ExecutionStepType.RAG_RETRIEVE, "按条件检索知识依据", {"policy": "conditional"}, optional=True),
                self._step(plan_id, session_id, ExecutionStepType.EVIDENCE_FUSION, "融合诊断证据", {}),
                self._step(plan_id, session_id, ExecutionStepType.REPORT_GENERATION, "按条件生成诊断报告", {"policy": "conditional"}, optional=True),
            ]

        if intent.intent == IntentType.REPORT_GENERATION:
            return [
                self._step(plan_id, session_id, ExecutionStepType.LOAD_SESSION_EVIDENCE, "加载会话证据", {}),
                self._step(plan_id, session_id, ExecutionStepType.RAG_RETRIEVE, "按需补充报告引用", {"policy": "conditional"}, optional=True),
                self._step(plan_id, session_id, ExecutionStepType.REPORT_GENERATION, "生成 Markdown 报告", {}),
            ]

        return [self._step(plan_id, session_id, ExecutionStepType.USER_INPUT, "请求用户澄清", {"message": message})]

    def _step(
        self,
        plan_id: str,
        session_id: str,
        step_type: ExecutionStepType,
        name: str,
        step_input: Dict[str, Any],
        optional: bool = False,
    ) -> ExecutionStep:
        return ExecutionStep(
            id=f"step_{uuid.uuid4().hex}",
            plan_id=plan_id,
            session_id=session_id,
            type=step_type,
            name=name,
            input=step_input,
            metadata={"optional": optional},
        )
