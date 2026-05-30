"""Agent Harness orchestrator."""

import uuid
from datetime import datetime
from typing import Any, AsyncIterator, Dict, Optional

from ..adapters import MCPGateway, RAGClient
from ..llm import LLMRouter
from ..models import Message, Session
from ..models.config import LLMAssistanceConfig, OrchestratorConfig
from ..models.evidence import CreateEvidenceRequest, EvidenceConfidence, EvidenceType, RAGEvidenceMetadata, MCPObservationMetadata
from ..models.orchestration import ExecutionPlan, ExecutionPlanStatus, ExecutionStep, ExecutionStepStatus, IntentType, MCPNextStep, MCPSearchResult, OrchestratorState, PendingInput, PendingInputOption, SSEEventEnvelope
from ..storage import ConfigStore, SessionStore
from .execution_planner import ExecutionPlanner
from .intent_router import IntentRouter
from .interaction_policy import InteractionPolicy
from .mcp_llm_assistant import MCPLLMOrchestrationAssistant
from .report_generator import ReportGenerator


class Orchestrator:
    """Coordinates RAG, MCP, evidence storage, and reporting."""

    def __init__(
        self,
        session_store: Optional[SessionStore] = None,
        rag_client: Optional[RAGClient] = None,
        mcp_gateway: Optional[MCPGateway] = None,
        config: Optional[OrchestratorConfig] = None,
        llm_router: Optional[LLMRouter] = None,
        llm_assistance_config: Optional[LLMAssistanceConfig] = None,
        llm_assistant: Optional[MCPLLMOrchestrationAssistant] = None,
    ):
        config_store = ConfigStore()
        self.config = config or config_store.get_orchestrator_config()
        self.session_store = session_store or SessionStore(config_store.get_storage_config().sqlite_path)
        self.rag_client = rag_client or RAGClient(config_store.get_rag_config())
        self.mcp_gateway = mcp_gateway or MCPGateway(config_store.get_mcp_harness_config())
        self.intent_router = IntentRouter(self.session_store)
        self.execution_planner = ExecutionPlanner()
        self.policy = InteractionPolicy(self.config)
        self.report_generator = ReportGenerator()
        self.llm_router = llm_router or LLMRouter(config_store.get_llm_router_config())
        self.llm_assistant = llm_assistant or MCPLLMOrchestrationAssistant(
            self.llm_router,
            llm_assistance_config or config_store.get_llm_assistance_config(),
        )

    async def close(self) -> None:
        await self.mcp_gateway.close()

    async def handle_message(self, session_id: Optional[str], message: str) -> AsyncIterator[SSEEventEnvelope]:
        session_id = session_id or f"ses_{uuid.uuid4().hex}"
        message_id = f"msg_{uuid.uuid4().hex}"
        self._append_message(session_id, "user", message, state=OrchestratorState.INTENT_DETECTED.value, message_id=message_id)
        yield self._event("message_start", session_id, {"message_id": message_id})

        intent = self.intent_router.route(message, session_id)
        yield self._event("intent_detected", session_id, intent.model_dump())

        plan = self.execution_planner.create_plan(session_id, message_id, message, intent)
        self.session_store.create_execution_plan(plan)
        yield self._event("execution_plan_created", session_id, self._plan_payload(plan))

        self.session_store.create_evidence(CreateEvidenceRequest(
            session_id=session_id,
            plan_id=plan.id,
            type=EvidenceType.USER_INPUT,
            source="user",
            content=message,
            summary="用户请求",
            confidence=EvidenceConfidence.HIGH,
            metadata={"intent": intent.intent.value, "extracted": intent.extracted},
        ))

        if intent.intent == IntentType.CHAT:
            step = self._find_step(plan, "chat_response")
            if step:
                yield self._start_step(step)
            content = self._chat_response()
            yield self._event("message_delta", session_id, {"content": content})
            if step:
                yield self._complete_step(step, {"content": content})
            self._append_message(session_id, "agent", content, state=OrchestratorState.COMPLETED.value)
            plan.status = ExecutionPlanStatus.COMPLETED
            self.session_store.update_execution_plan(plan)
            yield self._event("message_end", session_id, {"message_id": message_id, "state": OrchestratorState.COMPLETED.value})
            return

        if intent.intent in {IntentType.KNOWLEDGE_QA, IntentType.KNOWLEDGE_RETRIEVE}:
            response_parts = []
            async for event in self._handle_knowledge(session_id, message, plan):
                if event.event == "message_delta" and "content" in event.data:
                    response_parts.append(event.data["content"])
                yield event
            self._append_message(session_id, "agent", "\n".join(response_parts), state=OrchestratorState.COMPLETED.value)
            yield self._event("message_end", session_id, {"message_id": message_id, "state": OrchestratorState.COMPLETED.value})
            return

        if intent.intent in {IntentType.DIAGNOSIS, IntentType.PROFILING_ANALYSIS}:
            response_parts = []
            final_state = OrchestratorState.COMPLETED.value
            async for event in self._handle_diagnosis(session_id, message, intent.extracted, plan):
                if event.event == "analysis_result" and "summary" in event.data:
                    response_parts.append(event.data["summary"])
                if event.event == "user_input_required":
                    final_state = OrchestratorState.WAITING_USER_INPUT.value
                if event.event == "error":
                    response_parts.append(event.data.get("message") or event.data.get("error") or event.data.get("code", ""))
                yield event
            self._append_message(session_id, "agent", "\n".join(part for part in response_parts if part), state=final_state)
            yield self._event("message_end", session_id, {"message_id": message_id, "state": final_state})
            return

        if intent.intent == IntentType.REPORT_GENERATION:
            report = self._generate_and_save_report(session_id, message)
            yield self._event("report_ready", session_id, {
                "report_id": report["id"],
                "format": report["format"],
                "evidence_ids": report["evidence_ids"],
            })
            yield self._event("message_end", session_id, {"message_id": message_id, "state": OrchestratorState.COMPLETED.value})
            return

        yield self._event("user_input_required", session_id, {
            "input_type": "text",
            "question": "请补充你希望进行知识查询还是 profiling 性能诊断，并提供必要的 profiling 文件路径。",
            "reason": intent.reason,
            "options": [],
        })
        yield self._event("message_end", session_id, {"message_id": message_id, "state": OrchestratorState.WAITING_USER_INPUT.value})

    async def continue_with_input(self, session_id: str, user_input: Any) -> AsyncIterator[SSEEventEnvelope]:
        pending = self.session_store.get_active_pending_input(session_id)
        content = user_input if isinstance(user_input, str) else str(user_input)
        self._append_message(session_id, "user", content, state=OrchestratorState.INTENT_DETECTED.value)
        self.session_store.create_evidence(CreateEvidenceRequest(
            session_id=session_id,
            type=EvidenceType.USER_INPUT,
            source="user",
            content=content,
            summary="用户补充输入",
            confidence=EvidenceConfidence.HIGH,
            metadata={"pending_input_id": pending.id if pending else None},
        ))
        if not pending:
            async for event in self.handle_message(session_id, content):
                yield event
            return

        self.session_store.resolve_pending_input(pending.id)
        resume_action = pending.metadata.get("resume_action")
        if resume_action == "continue_mcp_with_args":
            arguments = self._parse_user_arguments(user_input)
            merged = {**pending.metadata.get("resolved_arguments", {}), **arguments}
            tool_name = pending.metadata.get("tool_name")
            if tool_name:
                async for event in self._execute_mcp_chain(
                    session_id,
                    tool_name,
                    merged,
                    int(pending.metadata.get("auto_step_count", 0)),
                    context=pending.metadata.get("context", {}),
                ):
                    yield event
                yield self._event("message_end", session_id, {"state": OrchestratorState.COMPLETED.value})
                return

        if resume_action == "select_playbook":
            async for event in self._handle_diagnosis(session_id, pending.metadata.get("original_message", content), {"selected_playbook": content.strip()}):
                yield event
            yield self._event("message_end", session_id, {"state": OrchestratorState.COMPLETED.value})
            return

        if resume_action == "execute_next_tool":
            confirmed = content.strip().lower() in {"true", "yes", "y", "1", "确认", "继续", "是"}
            if confirmed:
                tool_name = pending.metadata.get("tool_name")
                if tool_name:
                    async for event in self._execute_mcp_chain(
                        session_id,
                        tool_name,
                        pending.metadata.get("resolved_arguments", {}),
                        int(pending.metadata.get("auto_step_count", 0)),
                        context=pending.metadata.get("context", {}),
                    ):
                        yield event
                    yield self._event("message_end", session_id, {"state": OrchestratorState.COMPLETED.value})
                    return
            yield self._event("analysis_result", session_id, {"summary": "用户未确认继续执行 MCP 工具。", "confidence": "medium"})
            yield self._event("message_end", session_id, {"state": OrchestratorState.COMPLETED.value})
            return

        async for event in self.handle_message(session_id, content):
            yield event

    async def _handle_knowledge(self, session_id: str, message: str, plan: Optional[ExecutionPlan] = None) -> AsyncIterator[SSEEventEnvelope]:
        step = self._find_first_step(plan, {"rag_qa", "rag_retrieve"})
        if step:
            yield self._start_step(step)
        yield self._event("rag_retrieval", session_id, {"query": message, "status": "started"})
        try:
            result = await self.rag_client.retrieve(message)
            evidence_ids = self._save_rag_evidence(session_id, result, plan)
            yield self._event("rag_retrieval", session_id, {
                "query": message,
                "top_k": len(result.results),
                "evidence_ids": evidence_ids,
                "result_count": len(result.results),
                "elapsed_ms": result.elapsed_ms,
            })
            if step:
                yield self._complete_step(step, {"evidence_ids": evidence_ids, "result_count": len(result.results), "elapsed_ms": result.elapsed_ms})
            summary = self._summarize_rag_results(result)
            yield self._event("message_delta", session_id, {"content": summary})
            if plan:
                plan.status = ExecutionPlanStatus.COMPLETED
                self.session_store.update_execution_plan(plan)
        except Exception as exc:
            evidence = self.session_store.create_evidence(CreateEvidenceRequest(
                session_id=session_id,
                plan_id=plan.id if plan else None,
                step_id=step.id if step else None,
                type=EvidenceType.SYSTEM_EVENT,
                source="rag_client",
                content=str(exc),
                summary="RAG 服务不可用",
                confidence=EvidenceConfidence.HIGH,
                metadata={"code": "RAG_UNAVAILABLE"},
            ))
            if step:
                yield self._fail_step(step, "RAG_UNAVAILABLE", str(exc))
            yield self._event("error", session_id, {"code": "RAG_UNAVAILABLE", "message": str(exc), "evidence_id": evidence.id, "recoverable": True})

    async def _handle_diagnosis(self, session_id: str, message: str, extracted: Dict[str, Any], plan: Optional[ExecutionPlan] = None) -> AsyncIterator[SSEEventEnvelope]:
        search_step = self._find_step(plan, "mcp_search")
        if search_step:
            yield self._start_step(search_step)
        try:
            tools = await self.mcp_gateway.ensure_tools_loaded()
            playbook_selection = await self.llm_assistant.select_playbook_from_tools(message, tools, {"extracted": extracted})
            search_query = playbook_selection.get("query") or await self.llm_assistant.rewrite_query(message, {"extracted": extracted})
            selected_playbook = extracted.get("selected_playbook") or playbook_selection.get("select_playbook")
            search = await self.mcp_gateway.search_profiler_tools(search_query, selected_playbook)
            search.playbook_candidates = await self.llm_assistant.recommend_playbook_candidate(
                message,
                search.playbook_candidates,
                {"extracted": extracted, "search_query": search_query},
            )
            llm_selected_playbook = self._llm_selected_playbook(search.playbook_candidates)
            if search.requires_user_choice and llm_selected_playbook:
                search = await self.mcp_gateway.search_profiler_tools(search_query, llm_selected_playbook)
                search.metadata = {
                    **search.metadata,
                    "llm_selected_playbook": llm_selected_playbook,
                    "llm_auto_selection": True,
                }
            search_evidence = self.session_store.create_evidence(CreateEvidenceRequest(
                session_id=session_id,
                plan_id=plan.id if plan else None,
                type=EvidenceType.MCP_OBSERVATION,
                source="msinsight_mcp",
                step_id=search_step.id if search_step else None,
                content=search.text,
                summary="MCP playbook 搜索结果",
                confidence=EvidenceConfidence.MEDIUM,
                metadata={
                    "mcp_tool": "search_profiler_tools",
                    "auto_selected_playbook": search.auto_selected_playbook,
                    "selected_playbook": search.selected_playbook,
                    "initial_step": search.initial_step.model_dump(by_alias=True) if search.initial_step else None,
                    "suggested_arguments": search.suggested_arguments,
                    "elapsed_ms": search.elapsed_ms,
                    "raw": search.raw,
                    "original_query": message,
                    "search_query": search_query,
                    "llm_query_rewritten": search_query != message,
                    "llm_selected_playbook": search.metadata.get("llm_selected_playbook") or playbook_selection.get("select_playbook"),
                    "llm_auto_selection": search.metadata.get("llm_auto_selection", False) or bool(playbook_selection.get("select_playbook")),
                    "llm_playbook_selection": playbook_selection,
                },
            ))
            yield self._event("mcp_tool_result", session_id, {
                "tool_name": "search_profiler_tools",
                "evidence_id": search_evidence.id,
                "status": search.status,
                "elapsed_ms": search.elapsed_ms,
                "playbook_candidates": search.playbook_candidates,
                "auto_selected_playbook": search.auto_selected_playbook,
            })
            if search_step:
                search_step.evidence_ids.append(search_evidence.id)
                yield self._complete_step(search_step, {
                    "evidence_id": search_evidence.id,
                    "status": search.status,
                    "elapsed_ms": search.elapsed_ms,
                    "auto_selected_playbook": search.auto_selected_playbook,
                })
            if plan:
                plan.evidence_ids.append(search_evidence.id)
                self.session_store.update_execution_plan(plan)
        except Exception as exc:
            evidence = self.session_store.create_evidence(CreateEvidenceRequest(
                session_id=session_id,
                plan_id=plan.id if plan else None,
                step_id=search_step.id if search_step else None,
                type=EvidenceType.SYSTEM_EVENT,
                source="mcp_gateway",
                content=str(exc),
                summary="MCP 服务不可用，无法基于真实 profiling 数据验证",
                confidence=EvidenceConfidence.HIGH,
                metadata={"code": "MCP_UNAVAILABLE", "mcp_trace": self.mcp_gateway._last_trace()},
            ))
            if search_step:
                yield self._fail_step(search_step, "MCP_UNAVAILABLE", str(exc))
            yield self._event("error", session_id, {
                "code": "MCP_UNAVAILABLE",
                "message": str(exc),
                "evidence_id": evidence.id,
                "recoverable": True,
                "degradation_options": [{"label": "降级为 RAG 知识建议", "value": "fallback_to_rag"}],
            })
            yield self._require_rag_fallback(session_id, message, plan)
            return

        pending = await self._pending_from_search(session_id, message, search, extracted, plan)
        if pending:
            self.session_store.create_pending_input(pending)
            if plan:
                plan.status = ExecutionPlanStatus.WAITING_USER
                self.session_store.update_execution_plan(plan)
            yield self._event("user_input_required", session_id, pending.model_dump(mode="json"))
            return

        initial_step = search.initial_step
        resolved_args = self._resolve_step_arguments(initial_step, search.suggested_arguments, {"message": message, **extracted}) if initial_step else {}
        resolved_args = await self.llm_assistant.extract_parameters(message, initial_step, resolved_args, {"message": message, **extracted})
        context = {
            "message": message,
            "path": extracted.get("path"),
            "selected_playbook": search.selected_playbook or search.auto_selected_playbook,
            "search_suggested_arguments": search.suggested_arguments,
        }
        async for event in self._execute_mcp_chain(session_id, initial_step.tool_name, resolved_args, 0, plan, context=context):
            yield event

        if self._should_call_rag_after_mcp(message):
            try:
                rag_result = await self.rag_client.retrieve(message)
                rag_evidence_ids = self._save_rag_evidence(session_id, rag_result, plan)
                yield self._event("rag_retrieval", session_id, {
                    "query": message,
                    "evidence_ids": rag_evidence_ids,
                    "result_count": len(rag_result.results),
                    "elapsed_ms": rag_result.elapsed_ms,
                    "policy": "after_mcp",
                })
            except Exception as exc:
                evidence = self.session_store.create_evidence(CreateEvidenceRequest(
                    session_id=session_id,
                    plan_id=plan.id if plan else None,
                    type=EvidenceType.SYSTEM_EVENT,
                    source="rag_client",
                    content=str(exc),
                    summary="RAG 检索失败，诊断仅包含 MCP 实测证据",
                    confidence=EvidenceConfidence.MEDIUM,
                    metadata={"code": "RAG_UNAVAILABLE"},
                ))
                yield self._event("error", session_id, {"code": "RAG_UNAVAILABLE", "message": str(exc), "evidence_id": evidence.id, "recoverable": True})

        yield self._event("analysis_result", session_id, {"summary": "MCP 实测分析已完成，已保存工具观测结果。", "confidence": "medium"})

        if self._should_generate_report(message):
            report = self._generate_and_save_report(session_id, message, plan.id if plan else None)
            yield self._event("report_ready", session_id, {"report_id": report["id"], "format": report["format"], "evidence_ids": report["evidence_ids"]})
        if plan:
            plan.status = ExecutionPlanStatus.COMPLETED
            self.session_store.update_execution_plan(plan)

    async def _execute_mcp_chain(
        self,
        session_id: str,
        initial_tool: str,
        initial_args: Dict[str, Any],
        auto_count: int,
        plan: Optional[ExecutionPlan] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[SSEEventEnvelope]:
        context = context or {}
        current_tool = initial_tool
        current_args = initial_args
        while current_tool:
            step = self._find_step(plan, "mcp_execute")
            if step:
                step.input = {"tool_name": current_tool, "arguments": current_args}
                yield self._start_step(step)
            yield self._event("mcp_tool_start", session_id, {"tool_name": "execute_profiler_tool", "internal_tool_name": current_tool, "arguments_preview": current_args})
            try:
                result = await self.mcp_gateway.execute_profiler_tool(current_tool, current_args)
            except Exception as exc:
                if step:
                    yield self._fail_step(step, "MCP_TOOL_FAILED", str(exc))
                failure_trace = self.mcp_gateway._last_trace()
                self.session_store.create_evidence(CreateEvidenceRequest(
                    session_id=session_id,
                    plan_id=plan.id if plan else None,
                    step_id=step.id if step else None,
                    type=EvidenceType.SYSTEM_EVENT,
                    source="mcp_gateway",
                    content=str(exc),
                    summary="MCP 工具执行失败",
                    confidence=EvidenceConfidence.HIGH,
                    metadata={"code": "MCP_TOOL_FAILED", "mcp_trace": failure_trace},
                ))
                yield self._event("error", session_id, {"code": "MCP_TOOL_FAILED", "message": str(exc), "recoverable": True})
                return
            metadata = MCPObservationMetadata(
                mcp_tool="execute_profiler_tool",
                internal_tool=current_tool,
                arguments=current_args,
                next_step=result.next_step.model_dump(by_alias=True) if result.next_step else None,
                elapsed_ms=result.elapsed_ms,
                status=result.status,
                raw=result.raw,
            )
            evidence = self.session_store.create_evidence(CreateEvidenceRequest(
                session_id=session_id,
                plan_id=plan.id if plan else None,
                step_id=step.id if step else None,
                type=EvidenceType.MCP_OBSERVATION,
                source="msinsight_mcp",
                content=result.text,
                summary=f"MCP 工具 `{current_tool}` 执行结果",
                confidence=EvidenceConfidence.MEDIUM,
                metadata=metadata.model_dump(),
            ))
            yield self._event("mcp_tool_result", session_id, {
                "tool_name": current_tool,
                "evidence_id": evidence.id,
                "status": result.status,
                "next_action": result.next_step.model_dump(by_alias=True) if result.next_step else None,
                "elapsed_ms": result.elapsed_ms,
            })
            if step:
                step.evidence_ids.append(evidence.id)
                yield self._complete_step(step, {
                    "tool_name": current_tool,
                    "evidence_id": evidence.id,
                    "status": result.status,
                    "next_action": result.next_step.model_dump(by_alias=True) if result.next_step else None,
                    "elapsed_ms": result.elapsed_ms,
                })
            if plan and evidence.id not in plan.evidence_ids:
                plan.evidence_ids.append(evidence.id)
                self.session_store.update_execution_plan(plan)

            decision = self.policy.decide_after_mcp_result(session_id, result, auto_count)
            if decision.action == "continue_auto" and result.next_step and result.next_step.tool_name:
                next_args = self._resolve_step_arguments(result.next_step, {}, context)
                next_args = await self.llm_assistant.extract_parameters(context.get("message", ""), result.next_step, next_args, context)
                missing = self._missing_required_arguments(result.next_step, next_args)
                if missing:
                    pending = PendingInput(
                        id=f"pin_{uuid.uuid4().hex}",
                        session_id=session_id,
                        plan_id=plan.id if plan else None,
                        input_type="params",
                        question=f"下一步 `{result.next_step.tool_name}` 需要参数：{', '.join(missing)}。请以 JSON 对象补充参数。",
                        reason="MCP 下一步 schema 中存在无法从上下文安全推导的必填参数。",
                        metadata={
                            "resume_action": "continue_mcp_with_args",
                            "tool_name": result.next_step.tool_name,
                            "required": missing,
                            "schema": result.next_step.schema_,
                            "resolved_arguments": next_args,
                            "context": context,
                            "auto_step_count": auto_count,
                        },
                    )
                    self.session_store.create_pending_input(pending)
                    yield self._event("user_input_required", session_id, pending.model_dump(mode="json"))
                    return
                auto_count += 1
                current_tool = result.next_step.tool_name
                current_args = next_args
                continue
            if decision.action == "require_user_input" and decision.pending_input:
                resolved_arguments = self._resolve_step_arguments(result.next_step, {}, context) if result.next_step else {}
                if result.next_step:
                    resolved_arguments = await self.llm_assistant.extract_parameters(context.get("message", ""), result.next_step, resolved_arguments, context)
                decision.pending_input.metadata = {
                    **decision.pending_input.metadata,
                    "context": context,
                    "auto_step_count": auto_count,
                    "resolved_arguments": resolved_arguments,
                }
                self.session_store.create_pending_input(decision.pending_input)
                yield self._event("user_input_required", session_id, decision.pending_input.model_dump(mode="json"))
                return
            yield self._event("analysis_result", session_id, {"summary": decision.reason, "confidence": "medium"})
            break

    async def _pending_from_search(
        self,
        session_id: str,
        message: str,
        search: MCPSearchResult,
        extracted: Dict[str, Any],
        plan: Optional[ExecutionPlan] = None,
    ) -> Optional[PendingInput]:
        if search.requires_user_choice:
            return PendingInput(
                id=f"pin_{uuid.uuid4().hex}",
                session_id=session_id,
                plan_id=plan.id if plan else None,
                input_type="choice",
                question="MCP 返回多个可选 profiling 剧本，请选择要执行的剧本。",
                reason=search.text[:1000],
                options=[
                    PendingInputOption(
                        label=str(candidate.get("name") or candidate.get("id") or candidate.get("playbook_id") or candidate.get("playbookId")),
                        value=str(candidate.get("id") or candidate.get("playbook_id") or candidate.get("playbookId") or candidate.get("name")),
                        description=str(candidate.get("description") or candidate.get("summary") or ""),
                    )
                    for candidate in search.playbook_candidates
                ],
                metadata={"resume_action": "select_playbook", "original_message": message, "candidates": search.playbook_candidates},
            )

        if not search.initial_step or not search.initial_step.tool_name:
            return PendingInput(
                id=f"pin_{uuid.uuid4().hex}",
                session_id=session_id,
                plan_id=plan.id if plan else None,
                input_type="text",
                question="MCP 已返回剧本搜索结果，但未提供可执行的首个步骤。请补充要执行的 profiler 工具或调整问题描述。",
                reason=search.text[:1000],
                metadata={"resume_action": "select_playbook", "original_message": message, "raw": search.raw},
            )

        resolved = self._resolve_step_arguments(search.initial_step, search.suggested_arguments, {"message": message, **extracted})
        resolved = await self.llm_assistant.extract_parameters(message, search.initial_step, resolved, {"message": message, **extracted})
        missing = self._missing_required_arguments(search.initial_step, resolved)
        if missing:
            return PendingInput(
                id=f"pin_{uuid.uuid4().hex}",
                session_id=session_id,
                plan_id=plan.id if plan else None,
                input_type="params",
                question=f"MCP 首步 `{search.initial_step.tool_name}` 需要参数：{', '.join(missing)}。请以 JSON 对象补充参数。",
                reason="MCP 首步 schema 中存在无法从上下文安全推导的必填参数。",
                metadata={
                    "resume_action": "continue_mcp_with_args",
                    "tool_name": search.initial_step.tool_name,
                    "required": missing,
                    "schema": search.initial_step.schema_,
                    "resolved_arguments": resolved,
                    "context": {"message": message, "path": extracted.get("path"), "selected_playbook": search.selected_playbook or search.auto_selected_playbook},
                },
            )
        return None

    def _llm_selected_playbook(self, candidates: list[Dict[str, Any]]) -> Optional[str]:
        if not candidates:
            return None
        candidate = candidates[0]
        confidence = candidate.get("llm_confidence")
        candidate_id = candidate.get("id") or candidate.get("playbook_id") or candidate.get("playbookId") or candidate.get("name")
        if candidate_id and isinstance(confidence, (int, float)) and confidence >= 0.8:
            return str(candidate_id)
        return None

    def _resolve_step_arguments(self, step: Optional[MCPNextStep], suggested: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        arguments = dict(suggested or {})
        if not step or not step.schema_:
            return arguments
        properties = step.schema_.get("properties", {})
        if not isinstance(properties, dict):
            return arguments
        path = context.get("path")
        for name in properties:
            if name in arguments:
                continue
            lowered = name.lower()
            if path and lowered in {"path", "file_path", "filepath", "trace_path", "trace_file", "data_path"}:
                arguments[name] = path
            elif lowered in {"query", "question", "user_query", "goal"} and context.get("message"):
                arguments[name] = context["message"]
        return arguments

    def _missing_required_arguments(self, step: Optional[MCPNextStep], arguments: Dict[str, Any]) -> list[str]:
        if not step or not step.schema_:
            return []
        required = step.schema_.get("required", [])
        if not isinstance(required, list):
            return []
        missing = []
        for name in required:
            value = arguments.get(str(name))
            if value is None or value == "":
                missing.append(str(name))
        return missing

    def _parse_user_arguments(self, user_input: Any) -> Dict[str, Any]:
        if isinstance(user_input, dict):
            return user_input
        if not isinstance(user_input, str):
            return {"value": user_input}
        import json
        try:
            parsed = json.loads(user_input)
        except json.JSONDecodeError:
            return {"value": user_input}
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    def _require_rag_fallback(self, session_id: str, message: str, plan: Optional[ExecutionPlan] = None) -> SSEEventEnvelope:
        pending = PendingInput(
            id=f"pin_{uuid.uuid4().hex}",
            session_id=session_id,
            plan_id=plan.id if plan else None,
            input_type="confirm",
            question="MCP 服务不可用，是否降级为 RAG 知识建议？",
            reason="降级后只能基于知识库给出建议，不能基于真实 profiling 数据验证。",
            options=[
                PendingInputOption(label="降级为 RAG 建议", value="fallback_to_rag", description="继续查询知识库，但结论不包含 MCP 实测证据"),
                PendingInputOption(label="暂不降级", value="cancel", description="停止当前诊断"),
            ],
            recommended_value="fallback_to_rag",
            metadata={"resume_action": "fallback_to_rag", "original_message": message},
        )
        self.session_store.create_pending_input(pending)
        if plan:
            plan.status = ExecutionPlanStatus.WAITING_USER
            self.session_store.update_execution_plan(plan)
        return self._event("user_input_required", session_id, pending.model_dump(mode="json"))

    async def _handle_rag_fallback(self, session_id: str, message: str, plan: Optional[ExecutionPlan] = None) -> AsyncIterator[SSEEventEnvelope]:
        step = self._find_first_step(plan, {"rag_qa", "rag_retrieve"})
        if step:
            yield self._start_step(step)
        yield self._event("rag_retrieval", session_id, {"query": message, "status": "started", "mode": "mcp_unavailable_fallback"})
        try:
            result = await self.rag_client.retrieve(message)
            evidence_ids = self._save_rag_evidence(session_id, result, plan)
            if step:
                step.evidence_ids.extend(evidence_ids)
                yield self._complete_step(step, {"evidence_ids": evidence_ids, "result_count": len(result.results), "elapsed_ms": result.elapsed_ms})
            yield self._event("rag_retrieval", session_id, {
                "query": message,
                "top_k": len(result.results),
                "evidence_ids": evidence_ids,
                "result_count": len(result.results),
                "elapsed_ms": result.elapsed_ms,
                "mode": "mcp_unavailable_fallback",
            })
            summary = "MCP 服务不可用，以下内容仅为基于知识库的建议，未经过真实 profiling 数据验证。\n\n" + self._summarize_rag_results(result)
            yield self._event("message_delta", session_id, {"content": summary})
            yield self._event("analysis_result", session_id, {
                "summary": summary,
                "confidence": "low",
                "evidence_ids": evidence_ids,
                "degraded": True,
                "degradation_reason": "mcp_unavailable",
            })
            self._append_message(session_id, "agent", summary, state=OrchestratorState.COMPLETED.value)
            if plan:
                plan.status = ExecutionPlanStatus.COMPLETED
                plan.updated_at = datetime.utcnow()
                self.session_store.update_execution_plan(plan)
        except Exception as exc:
            if step:
                yield self._fail_step(step, "RAG_UNAVAILABLE", str(exc))
            yield self._event("error", session_id, {"code": "RAG_UNAVAILABLE", "message": str(exc), "recoverable": False})

    def _save_rag_evidence(self, session_id: str, result, plan: Optional[ExecutionPlan] = None) -> list[str]:
        evidence_ids = []
        for index, item in enumerate(result.results, start=1):
            metadata = RAGEvidenceMetadata(
                query=result.query,
                score=item.score,
                doc_id=item.source.get("doc_id"),
                chunk_id=item.source.get("chunk_id") or item.metadata.get("chunk_id"),
                title=item.source.get("title") or item.metadata.get("title"),
                section_title=item.source.get("section_title") or item.metadata.get("section_title"),
                path=item.source.get("path") or item.metadata.get("path"),
                url=item.source.get("url") or item.metadata.get("url"),
                vector_score=item.metadata.get("vector_score"),
                keyword_score=item.metadata.get("keyword_score"),
                final_score=item.metadata.get("final_score"),
                rank=index,
                raw={"item": item.raw, "source": item.source, "metadata": item.metadata},
            )
            evidence = self.session_store.create_evidence(CreateEvidenceRequest(
                session_id=session_id,
                plan_id=plan.id if plan else None,
                type=EvidenceType.RAG_EVIDENCE,
                source="ms_rag",
                content=item.content,
                summary=item.content[:300],
                confidence=EvidenceConfidence.MEDIUM,
                metadata=metadata.model_dump(),
            ))
            evidence_ids.append(evidence.id)
            if plan and evidence.id not in plan.evidence_ids:
                plan.evidence_ids.append(evidence.id)
        if plan:
            self.session_store.update_execution_plan(plan)
        return evidence_ids

    def _summarize_rag_results(self, result) -> str:
        if not result.results:
            return "未检索到相关知识依据。"
        lines = ["已检索到相关知识依据："]
        for index, item in enumerate(result.results[:5], start=1):
            title = item.source.get("title") or item.source.get("path") or f"结果 {index}"
            lines.append(f"{index}. {title}: {item.content[:160]}")
        return "\n".join(lines)

    def _generate_and_save_report(self, session_id: str, user_goal: str, plan_id: Optional[str] = None) -> Dict[str, Any]:
        evidence = self.session_store.list_evidence(session_id)
        markdown = self.report_generator.generate_markdown_from_evidence(session_id, user_goal, evidence)
        return self.session_store.create_report(session_id, markdown, [item.id for item in evidence], plan_id=plan_id)

    def _should_call_rag_after_mcp(self, message: str) -> bool:
        return any(keyword in message for keyword in ["解释", "依据", "建议", "报告", "总结", "为什么", "原因", "快慢卡", "通信慢"])

    def _should_generate_report(self, message: str) -> bool:
        return any(keyword in message for keyword in ["报告", "总结", "复盘", "整理成文档", "整理成方案"])

    def _chat_response(self) -> str:
        return "我是 MSInsight Agent Harness，可以帮助你查询性能定位知识、调用 MSInsight MCP 基于 profiling 数据执行诊断，并汇总 RAG 知识依据与 MCP 实测结果生成可审计报告。如果你要分析 profiling，请提供文件或目录路径以及希望定位的问题。"

    def _find_step(self, plan: Optional[ExecutionPlan], step_type: str) -> Optional[ExecutionStep]:
        if not plan:
            return None
        for step in plan.steps:
            if step.type.value == step_type:
                return step
        return None

    def _find_first_step(self, plan: Optional[ExecutionPlan], step_types: set[str]) -> Optional[ExecutionStep]:
        if not plan:
            return None
        for step in plan.steps:
            if step.type.value in step_types:
                return step
        return None

    def _start_step(self, step: ExecutionStep) -> SSEEventEnvelope:
        step.status = ExecutionStepStatus.RUNNING
        step.started_at = datetime.utcnow()
        step.updated_at = step.started_at
        self.session_store.update_execution_step(step)
        return self._event("execution_step_started", step.session_id, self._step_payload(step))

    def _complete_step(self, step: ExecutionStep, output: Dict[str, Any]) -> SSEEventEnvelope:
        step.status = ExecutionStepStatus.COMPLETED
        step.output = output
        step.completed_at = datetime.utcnow()
        if step.started_at:
            step.elapsed_ms = int((step.completed_at - step.started_at).total_seconds() * 1000)
        step.updated_at = step.completed_at
        self.session_store.update_execution_step(step)
        return self._event("execution_step_completed", step.session_id, self._step_payload(step))

    def _fail_step(self, step: ExecutionStep, code: str, message: str) -> SSEEventEnvelope:
        step.status = ExecutionStepStatus.FAILED
        step.error = {"code": code, "message": message}
        step.completed_at = datetime.utcnow()
        if step.started_at:
            step.elapsed_ms = int((step.completed_at - step.started_at).total_seconds() * 1000)
        step.updated_at = step.completed_at
        self.session_store.update_execution_step(step)
        return self._event("execution_step_failed", step.session_id, self._step_payload(step))

    def _plan_payload(self, plan: ExecutionPlan) -> Dict[str, Any]:
        return plan.model_dump(mode="json")

    def _step_payload(self, step: ExecutionStep) -> Dict[str, Any]:
        return step.model_dump(mode="json")

    def _append_message(self, session_id: str, role: str, content: str, state: str = OrchestratorState.COMPLETED.value, message_id: Optional[str] = None) -> None:
        session = self.session_store.load(session_id)
        now = datetime.utcnow()
        if not session:
            session = Session(id=session_id, created_at=now, updated_at=now)
        session.messages.append(Message(
            id=message_id or f"msg_{uuid.uuid4().hex}",
            role=role,
            content=content,
            timestamp=now,
        ))
        session.state = state
        session.updated_at = now
        self.session_store.save(session)

    def _event(self, event: str, session_id: Optional[str], data: Dict[str, Any]) -> SSEEventEnvelope:
        return SSEEventEnvelope(event=event, event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, timestamp=datetime.utcnow(), data=data)
