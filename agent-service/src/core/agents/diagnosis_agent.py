import asyncio
import uuid
from typing import Any, List, Optional, Dict
from .base import BaseWorkerAgent, AgentResult, AgentRequirement
from ...models.orchestration import PendingInputOption, MCPSearchResult, MCPNextStep
from ...models.evidence import CreateEvidenceRequest, EvidenceType, EvidenceConfidence, MCPObservationMetadata
from ..diagnosis import DiagnosisContextManager, ParameterResolver
from ..diagnosis.compact import compact_for_llm
from ..diagnosis.models import ConfidenceLevel, ParamSource, PendingStepState

class DiagnosisAgent(BaseWorkerAgent):
    """Agent specialized in diagnostic tasks, leveraging MCP tools and playbooks."""

    def __init__(self, mcp_gateway, session_store, policy, llm_assistant):
        self.mcp_gateway = mcp_gateway
        self.session_store = session_store
        self.policy = policy
        self.llm_assistant = llm_assistant
        self.parameter_resolver = ParameterResolver(llm_assistant)

    async def run(self, session_id: str, plan_step_id: str, goal: str, blackboard: dict) -> AgentResult:
        """Initial diagnostic execution: search playbooks and start chain with persistent context."""
        extracted = dict(blackboard.get("extracted", {}) or {})

        try:
            import re
            early_path_match = re.search(r'([a-zA-Z]:\\[^\s"\'<>]+|/[^\s"\'<>]+)', goal)
            if early_path_match and not extracted.get("path"):
                extracted["path"] = early_path_match.group(1).strip()

            context = DiagnosisContextManager.create(
                session_id=session_id,
                plan_id=plan_step_id or None,
                root_message=goal,
                extracted=extracted,
            )
            self.session_store.create_diagnosis_context(context)

            tools = await self.mcp_gateway.ensure_tools_loaded()
            compact = compact_for_llm(context, stage="playbook_selection")
            playbook_selection = await self.llm_assistant.select_playbook_from_tools(goal, tools, compact)
            search_query = playbook_selection.get("query") or await self.llm_assistant.rewrite_query(goal, compact)
            selected_playbook = extracted.get("selected_playbook") or playbook_selection.get("select_playbook")

            search = await self.mcp_gateway.search_profiler_tools(search_query, selected_playbook)
            context.selected_playbook = search.selected_playbook or search.auto_selected_playbook or selected_playbook
            DiagnosisContextManager.increment_revision(context)

            search.playbook_candidates = await self.llm_assistant.recommend_playbook_candidate(
                goal,
                search.playbook_candidates,
                compact_for_llm(context, stage="candidate_recommendation"),
            )

            evidence_id = self._save_search_evidence(session_id, plan_step_id, goal, search_query, search, playbook_selection)
            if evidence_id not in context.effective_evidence_ids:
                context.effective_evidence_ids.append(evidence_id)
            self.session_store.update_diagnosis_context(context)

            selected_candidate = self._llm_selected_playbook(search.playbook_candidates)
            if search.requires_user_choice and selected_candidate:
                search = await self.mcp_gateway.search_profiler_tools(search_query, selected_candidate)
                context.selected_playbook = search.selected_playbook or search.auto_selected_playbook or selected_candidate
                DiagnosisContextManager.increment_revision(context)
                self.session_store.update_diagnosis_context(context)

            if search.requires_user_choice:
                pending_id = f"pin_{uuid.uuid4().hex}"
                pending = PendingStepState(
                    pending_id=pending_id,
                    resume_action="select_playbook",
                    reason="playbook_choice_required",
                )
                DiagnosisContextManager.set_pending(context, pending)
                self.session_store.update_diagnosis_context(context)
                return AgentResult(
                    status="suspended",
                    evidence_ids=[evidence_id],
                    requirement=AgentRequirement(
                        input_type="choice",
                        question="MCP 返回多个可选 profiling 剧本，请选择要执行的剧本。",
                        options=[
                            {
                                "label": str(c.get("name") or c.get("id")),
                                "value": str(c.get("id") or c.get("name")),
                                "description": str(c.get("description") or ""),
                            }
                            for c in search.playbook_candidates
                        ],
                        metadata={
                            "agent_type": "diagnosis",
                            "resume_action": "select_playbook",
                            "original_message": goal,
                            "candidates": search.playbook_candidates,
                            "diagnosis_id": context.diagnosis_id,
                            "context_revision": context.revision,
                            "pending_id": pending_id,
                        },
                    ),
                )

            if not search.initial_step or not search.initial_step.tool_name:
                pending_id = f"pin_{uuid.uuid4().hex}"
                DiagnosisContextManager.set_pending(context, PendingStepState(
                    pending_id=pending_id,
                    resume_action="select_playbook",
                    reason="missing_initial_step",
                ))
                self.session_store.update_diagnosis_context(context)
                return AgentResult(
                    status="suspended",
                    evidence_ids=[evidence_id],
                    requirement=AgentRequirement(
                        input_type="text",
                        question="MCP 已返回剧本搜索结果，但未提供可执行的首个步骤。请补充要执行的 profiler 工具或调整问题描述。",
                        metadata={
                            "agent_type": "diagnosis",
                            "resume_action": "select_playbook",
                            "original_message": goal,
                            "diagnosis_id": context.diagnosis_id,
                            "context_revision": context.revision,
                            "pending_id": pending_id,
                        },
                    ),
                )

            initial_step = search.initial_step
            resolution = await self.parameter_resolver.resolve_for_step(
                context,
                initial_step,
                suggested_args=search.suggested_arguments,
                current_user_input=goal,
            )
            if resolution.missing_required or resolution.needs_confirmation:
                pending_id = f"pin_{uuid.uuid4().hex}"
                metadata = {
                    "agent_type": "diagnosis",
                    "resume_action": "continue_mcp_with_args",
                    "tool_name": initial_step.tool_name,
                    "required": resolution.missing_required,
                    "resolved_arguments": resolution.arguments,
                    "param_sources": resolution.param_sources,
                    "llm_assistance": resolution.llm_assistance,
                    "tool_schema": initial_step.schema_,
                    "tool_schema_hash": DiagnosisContextManager.schema_hash(initial_step.schema_),
                    "diagnosis_id": context.diagnosis_id,
                    "context_revision": context.revision,
                }
                resolution = self._apply_single_option_autofill(resolution, initial_step, context, metadata)
                if not resolution.missing_required and not resolution.needs_confirmation:
                    chain_result = await self._execute_tool_and_check_next(
                        session_id,
                        plan_step_id,
                        initial_step.tool_name,
                        resolution.arguments,
                        0,
                        context,
                    )
                    chain_result.evidence_ids.append(evidence_id)
                    return chain_result
                pending = PendingStepState(
                    pending_id=pending_id,
                    resume_action="continue_mcp_with_args",
                    tool_name=initial_step.tool_name,
                    tool_schema=initial_step.schema_,
                    tool_schema_hash=DiagnosisContextManager.schema_hash(initial_step.schema_),
                    resolved_arguments=resolution.arguments,
                    required_missing=resolution.missing_required,
                    reason=resolution.question_reason or "parameter_confirmation_required",
                )
                metadata.update({"required": resolution.missing_required, "missing_required": resolution.missing_required, "resolved_arguments": resolution.arguments, "pending_id": pending_id})
                DiagnosisContextManager.set_pending(context, pending)
                self.session_store.update_diagnosis_context(context)
                return AgentResult(
                    status="suspended",
                    evidence_ids=[evidence_id],
                    requirement=self._build_suspension_requirement(
                        resolution.missing_required,
                        initial_step.tool_name,
                        context,
                        metadata,
                    ),
                )

            chain_result = await self._execute_tool_and_check_next(
                session_id,
                plan_step_id,
                initial_step.tool_name,
                resolution.arguments,
                0,
                context,
            )
            chain_result.evidence_ids.append(evidence_id)
            return chain_result

        except Exception as exc:
            return AgentResult(status="failed", error_msg=str(exc))

    def _is_complex_sentence(self, text: str) -> bool:
        """Heuristic to determine if input is a conversational sentence rather than a raw value."""
        return len(text) > 20 or any(char in text for char in ["，", "。", "！", "？", "帮我", "请", "是什么"])

    async def resume(self, session_id: str, plan_step_id: str, user_input: Any, suspended_metadata: dict) -> AgentResult:
        """Resume execution from a suspended diagnosis context."""
        resume_action = suspended_metadata.get("resume_action")
        diagnosis_id = suspended_metadata.get("diagnosis_id")
        context = self.session_store.get_diagnosis_context(diagnosis_id) if diagnosis_id else None

        if resume_action == "select_playbook":
            original = suspended_metadata.get("original_message", "")
            extracted = {"selected_playbook": str(user_input).strip()}
            if context:
                DiagnosisContextManager.clear_pending(context, suspended_metadata.get("pending_id"))
                extracted.update(context.known_params)
                self.session_store.update_diagnosis_context(context)
            return await self.run(session_id, plan_step_id, original, {"extracted": extracted})

        if resume_action == "continue_mcp_with_args":
            if not context:
                return AgentResult(status="failed", error_msg="Missing diagnosis context for resume")
            context.latest_user_input = str(user_input)
            DiagnosisContextManager.clear_pending(context, suspended_metadata.get("pending_id"))

            tool_name = suspended_metadata.get("tool_name")
            tool_schema = suspended_metadata.get("tool_schema") or suspended_metadata.get("schema") or {}
            required_missing = suspended_metadata.get("required", [])
            resolved = suspended_metadata.get("resolved_arguments", {})
            step = MCPNextStep(tool_name=tool_name, schema=tool_schema)
            resolution = await self.parameter_resolver.resolve_for_step(
                context,
                step,
                existing_args=resolved,
                current_user_input=user_input,
                previous_missing=required_missing,
            )
            if resolution.missing_required or resolution.needs_confirmation:
                pending_id = f"pin_{uuid.uuid4().hex}"
                pending = PendingStepState(
                    pending_id=pending_id,
                    resume_action="continue_mcp_with_args",
                    tool_name=tool_name,
                    tool_schema=tool_schema,
                    tool_schema_hash=DiagnosisContextManager.schema_hash(tool_schema),
                    resolved_arguments=resolution.arguments,
                    required_missing=resolution.missing_required or required_missing,
                    auto_step_count=int(suspended_metadata.get("auto_step_count", 0)),
                    reason=resolution.question_reason or "parameter_confirmation_required",
                )
                DiagnosisContextManager.set_pending(context, pending)
                self.session_store.update_diagnosis_context(context)
                return AgentResult(
                    status="suspended",
                    requirement=self._build_suspension_requirement(
                        pending.required_missing,
                        tool_name,
                        context,
                        {
                            "agent_type": "diagnosis",
                            "resume_action": "continue_mcp_with_args",
                            "tool_name": tool_name,
                            "required": pending.required_missing,
                            "resolved_arguments": resolution.arguments,
                            "tool_schema": tool_schema,
                            "tool_schema_hash": pending.tool_schema_hash,
                            "diagnosis_id": context.diagnosis_id,
                            "context_revision": context.revision,
                            "pending_id": pending_id,
                            "auto_step_count": pending.auto_step_count,
                        }
                    ),
                )

            auto_count = int(suspended_metadata.get("auto_step_count", 0))
            self.session_store.update_diagnosis_context(context)
            return await self._execute_tool_and_check_next(session_id, plan_step_id, tool_name, resolution.arguments, auto_count, context)

        return AgentResult(status="failed", error_msg=f"Unknown resume action: {resume_action}")

    def _build_suspension_requirement(self, missing_required: list[str], tool_name: str, context: Any, metadata: dict) -> AgentRequirement:
        schema = metadata.get("tool_schema") or {}
        fields = []
        top_options = []
        for name in missing_required:
            field_options = self._collect_field_options(name, context=context, metadata=metadata, schema=schema)
            field = {
                "name": name,
                "label": self._field_label(name),
                "type": "select" if field_options else "string",
                "required": True,
                "description": self._field_description(name, schema, metadata),
                "options": field_options,
            }
            fields.append(field)
        if len(fields) == 1 and fields[0].get("type") == "select":
            top_options = fields[0].get("options", [])
        enhanced_metadata = {
            **metadata,
            "missing_required": missing_required,
            "fields": fields,
        }
        question = self._deterministic_question(tool_name, missing_required, enhanced_metadata)
        return AgentRequirement(
            input_type="params",
            question=question,
            options=top_options,
            metadata=enhanced_metadata,
        )

    def _field_label(self, name: str) -> str:
        return {"groupIdHash": "通信组", "iterationId": "迭代 ID"}.get(name, name)

    def _field_description(self, name: str, schema: dict, metadata: dict) -> str:
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        prop = properties.get(name, {}) if isinstance(properties, dict) else {}
        if isinstance(prop, dict) and prop.get("description"):
            return str(prop.get("description"))
        for item in metadata.get("required_inputs", []) or []:
            if isinstance(item, dict) and item.get("name") == name and item.get("description"):
                return str(item.get("description"))
        return ""

    def _deterministic_question(self, tool_name: str, missing_required: list[str], metadata: dict) -> str:
        source_lines = []
        for entry in (metadata.get("param_sources") or {}).values():
            if isinstance(entry, dict) and entry.get("display"):
                source_lines.append(str(entry["display"]))
        if "groupIdHash" in missing_required:
            prefix = "已完成通信组耗时分析。下一步将定位引发通信阻塞的 Slow Rank。"
            if source_lines:
                prefix += "".join(f"{line}。" for line in source_lines)
            return f"{prefix}请选择要继续分析的通信组。"
        return f"下一步 `{tool_name}` 需要参数：{', '.join(missing_required)}。请补充参数。"

    def _collect_field_options(self, field_name: str, *, context: Any, metadata: dict, schema: dict) -> list[dict]:
        options: list[dict] = []
        for item in metadata.get("required_inputs", []) or []:
            if isinstance(item, dict) and item.get("name") == field_name:
                options.extend(self._normalize_options(item.get("options"), field_name))
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        prop = properties.get(field_name, {}) if isinstance(properties, dict) else {}
        if isinstance(prop, dict):
            options.extend(self._normalize_options(prop.get("enum") or prop.get("options"), field_name))
        known_params = context.get("known_params", {}) if isinstance(context, dict) else getattr(context, "known_params", {})
        produced = self._latest_produced_params(context)
        options.extend(self._options_from_mapping({k: metadata.get(k) for k in ("candidate_inputs", f"{field_name}_options", f"{field_name}Options", f"{field_name}List", f"{field_name}s", "candidates", "groups", "group_candidates", "data")}, field_name))
        for source in (known_params, produced):
            options.extend(self._options_from_mapping(source, field_name))
        return self._dedupe_options(options)

    def _latest_produced_params(self, context: Any) -> dict:
        steps = getattr(context, "completed_steps", None) or []
        if not steps:
            return {}
        latest = steps[-1]
        summary = getattr(latest, "result_summary", {}) or {}
        produced = summary.get("produced_params")
        return produced if isinstance(produced, dict) else {}

    def _options_from_mapping(self, source: Any, field_name: str) -> list[dict]:
        if not isinstance(source, dict):
            return []
        keys = [
            f"{field_name}_options", f"{field_name}Options", f"{field_name}List",
            f"{field_name}s", "candidates", "candidate_inputs", "groups", "group_candidates", "data",
        ]
        values = []
        for key in keys:
            value = source.get(key)
            if key == "candidate_inputs" and isinstance(value, dict):
                value = value.get(field_name)
            if value:
                values.extend(value if isinstance(value, list) else [value])
        if not values and field_name == "groupIdHash":
            values.extend(self._find_objects_with_key(source, field_name))
        return self._normalize_options(values, field_name)

    def _find_objects_with_key(self, value: Any, field_name: str) -> list[dict]:
        found = []
        if isinstance(value, dict):
            if field_name in value:
                found.append(value)
            for child in value.values():
                found.extend(self._find_objects_with_key(child, field_name))
        elif isinstance(value, list):
            for item in value:
                found.extend(self._find_objects_with_key(item, field_name))
        return found

    def _normalize_options(self, values: Any, field_name: str) -> list[dict]:
        if not values:
            return []
        items = values if isinstance(values, list) else [values]
        options = []
        for item in items:
            if isinstance(item, dict):
                if "label" in item and "value" in item:
                    options.append({"label": str(item["label"]), "value": item["value"], "description": str(item.get("description") or ""), "metadata": item.get("metadata", {})})
                elif field_name == "groupIdHash" and item.get("groupIdHash"):
                    options.append(self._format_group_option(item))
                elif item.get(field_name) is not None:
                    value = item.get(field_name)
                    options.append({"label": str(value), "value": value, "metadata": item})
            elif item not in (None, ""):
                options.append({"label": str(item), "value": item})
        return options

    def _format_group_option(self, item: dict) -> dict:
        group_hash = item.get("groupIdHash")
        pg_name = item.get("pgName") or item.get("parallelStrategy") or "通信组"
        duration = item.get("duration")
        ranks = item.get("rankList") or item.get("ranks")
        label_parts = [str(pg_name), str(group_hash)]
        if duration is not None:
            label_parts.append(f"{duration}ms")
        if ranks:
            label_parts.append(f"ranks: {','.join(map(str, ranks))}")
        return {"label": " / ".join(label_parts), "value": group_hash, "metadata": item}

    def _dedupe_options(self, options: list[dict]) -> list[dict]:
        seen = set()
        result = []
        for option in options:
            value = option.get("value")
            if value in (None, ""):
                continue
            key = str(value)
            if key in seen:
                continue
            seen.add(key)
            result.append(option)
        return result

    def _apply_single_option_autofill(self, resolution, step: MCPNextStep, context: Any, metadata: dict):
        if not resolution.missing_required or resolution.needs_confirmation:
            return resolution
        changed = False
        arguments = dict(resolution.arguments or {})
        param_sources = dict(resolution.param_sources or {})
        missing = list(resolution.missing_required)
        for field_name in list(missing):
            options = self._collect_field_options(field_name, context=context, metadata=metadata, schema=step.schema_ if step else {})
            if len(options) != 1:
                continue
            option = options[0]
            arguments[field_name] = option.get("value")
            param_sources[field_name] = {
                "value": option.get("value"),
                "source": "auto_selected_single_option",
                "display": f"已自动选择唯一{self._field_label(field_name)}：{option.get('label')}",
                "confidence": 1.0,
            }
            changed = True
        if not changed:
            return resolution
        required = step.schema_.get("required", []) if step and isinstance(step.schema_, dict) else []
        new_missing = [str(name) for name in required if arguments.get(str(name)) in (None, "")]
        return resolution.model_copy(update={
            "arguments": arguments,
            "missing_required": new_missing,
            "param_sources": param_sources,
            "question_reason": "missing_required_arguments" if new_missing else None,
        })

    async def _execute_tool_and_check_next(self, session_id: str, plan_step_id: str, tool_name: str, arguments: dict, auto_count: int, context) -> AgentResult:
        """Execute MCP tools in a bounded loop and persist diagnosis context after each step."""
        evidence_ids: list[str] = []
        current_tool = tool_name
        current_args = dict(arguments or {})
        current_auto = auto_count
        try:
            retry_state: Dict[str, Dict[str, int]] = {}
            while current_tool:
                result = await self.mcp_gateway.execute_profiler_tool(current_tool, current_args)
                text = result.text.strip() if result.text else ""
                if not result.control_flow and (text.startswith("ERROR:") or "EXECUTION BLOCKED:" in text):
                    self.session_store.update_diagnosis_context(context)
                    return AgentResult(status="failed", error_msg=text, evidence_ids=evidence_ids)

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
                    step_id=plan_step_id,
                    type=EvidenceType.MCP_OBSERVATION,
                    source="msinsight_mcp",
                    content=result.text,
                    summary=f"MCP 工具 `{current_tool}` 执行结果",
                    confidence=EvidenceConfidence.MEDIUM,
                    metadata=metadata.model_dump(),
                ))
                evidence_ids.append(evidence.id)
                DiagnosisContextManager.apply_step_result(
                    context,
                    tool_name=current_tool,
                    arguments=current_args,
                    argument_sources={key: "resolved" for key in current_args},
                    result_summary={"summary": result.text[:500], "produced_params": self._extract_produced_params(result.raw, text=result.text)},
                    evidence_id=evidence.id,
                    next_step=result.next_step.model_dump(by_alias=True) if result.next_step else None,
                    produced_params=self._extract_produced_params(result.raw, text=result.text),
                    elapsed_ms=result.elapsed_ms,
                )
                context.total_auto_steps += 1
                self.session_store.update_diagnosis_context(context)

                control_flow = result.control_flow
                if control_flow and control_flow.status == "BLOCKED":
                    key = f"{current_tool}:{control_flow.operation_id or hash(str(current_args))}:{control_flow.reason}"
                    state = retry_state.setdefault(key, {"attempts": 0, "total_wait_ms": 0})
                    delay_ms = min(control_flow.suggested_retry_after_ms or 3000, 10000)
                    if control_flow.retryable and state["attempts"] < 3 and state["total_wait_ms"] + delay_ms <= 30000:
                        state["attempts"] += 1
                        state["total_wait_ms"] += delay_ms
                        await asyncio.sleep(delay_ms / 1000)
                        continue
                    pending_id = f"pin_{uuid.uuid4().hex}"
                    pending = PendingStepState(
                        pending_id=pending_id,
                        resume_action="continue_mcp_with_args",
                        tool_name=current_tool,
                        resolved_arguments=current_args,
                        auto_step_count=current_auto,
                        reason=control_flow.reason or "blocked",
                    )
                    DiagnosisContextManager.set_pending(context, pending)
                    self.session_store.update_diagnosis_context(context)
                    return AgentResult(
                        status="suspended",
                        evidence_ids=evidence_ids,
                        requirement=AgentRequirement(
                            input_type="confirm",
                            question="后台任务仍未完成，是否稍后重试？",
                            metadata={"agent_type": "diagnosis", "resume_action": "continue_mcp_with_args", "tool_name": current_tool, "resolved_arguments": current_args, "diagnosis_id": context.diagnosis_id, "context_revision": context.revision, "pending_id": pending_id, "auto_step_count": current_auto, "control_flow": control_flow.model_dump(mode="json")},
                        ),
                    )

                if control_flow and control_flow.status == "RETRYABLE_ERROR":
                    key = f"{current_tool}:{hash(str(current_args))}:{control_flow.reason}"
                    state = retry_state.setdefault(key, {"attempts": 0, "total_wait_ms": 0})
                    delay_ms = min(control_flow.suggested_retry_after_ms or 3000, 10000)
                    if control_flow.retryable and state["attempts"] < 3 and state["total_wait_ms"] + delay_ms <= 30000:
                        state["attempts"] += 1
                        state["total_wait_ms"] += delay_ms
                        await asyncio.sleep(delay_ms / 1000)
                        continue
                    return AgentResult(status="failed", error_msg=result.error or control_flow.user_message or "MCP retryable error exceeded retry policy", evidence_ids=evidence_ids)

                if control_flow and control_flow.status == "FATAL_ERROR":
                    return AgentResult(status="failed", error_msg=result.error or control_flow.user_message or control_flow.developer_message or "MCP fatal error", evidence_ids=evidence_ids)

                if control_flow and control_flow.status == "NEEDS_USER_INPUT":
                    pending_id = f"pin_{uuid.uuid4().hex}"
                    missing = [item.name for item in control_flow.required_inputs]
                    required_inputs = [item.model_dump(mode="json") for item in control_flow.required_inputs]
                    pending = PendingStepState(
                        pending_id=pending_id,
                        resume_action="continue_mcp_with_args",
                        tool_name=current_tool,
                        resolved_arguments=current_args,
                        required_missing=missing,
                        auto_step_count=current_auto,
                        reason=control_flow.reason or "needs_user_input",
                    )
                    DiagnosisContextManager.set_pending(context, pending)
                    self.session_store.update_diagnosis_context(context)
                    requirement = self._build_suspension_requirement(
                        missing,
                        current_tool,
                        context,
                        {
                            "agent_type": "diagnosis",
                            "resume_action": "continue_mcp_with_args",
                            "tool_name": current_tool,
                            "required": missing,
                            "resolved_arguments": current_args,
                            "diagnosis_id": context.diagnosis_id,
                            "context_revision": context.revision,
                            "pending_id": pending_id,
                            "auto_step_count": current_auto,
                            "control_flow": control_flow.model_dump(mode="json"),
                            "required_inputs": required_inputs,
                        },
                    )
                    if control_flow.user_message:
                        requirement.question = control_flow.user_message
                    return AgentResult(status="suspended", evidence_ids=evidence_ids, requirement=requirement)

                decision = self.policy.decide_after_mcp_result(session_id, result, current_auto)
                if decision.action == "continue_auto" and result.next_step and result.next_step.tool_name:
                    resolution = await self.parameter_resolver.resolve_for_step(context, result.next_step)
                    if resolution.missing_required or resolution.needs_confirmation:
                        metadata = {
                            "agent_type": "diagnosis",
                            "resume_action": "continue_mcp_with_args",
                            "tool_name": result.next_step.tool_name,
                            "required": resolution.missing_required,
                            "resolved_arguments": resolution.arguments,
                            "param_sources": resolution.param_sources,
                            "llm_assistance": resolution.llm_assistance,
                            "tool_schema": result.next_step.schema_,
                            "tool_schema_hash": DiagnosisContextManager.schema_hash(result.next_step.schema_),
                            "diagnosis_id": context.diagnosis_id,
                            "context_revision": context.revision,
                            "auto_step_count": current_auto,
                        }
                        resolution = self._apply_single_option_autofill(resolution, result.next_step, context, metadata)
                        if not resolution.missing_required and not resolution.needs_confirmation:
                            current_tool = result.next_step.tool_name
                            current_args = resolution.arguments
                            current_auto += 1
                            continue
                        pending_id = f"pin_{uuid.uuid4().hex}"
                        pending = PendingStepState(
                            pending_id=pending_id,
                            resume_action="continue_mcp_with_args",
                            tool_name=result.next_step.tool_name,
                            tool_schema=result.next_step.schema_,
                            tool_schema_hash=DiagnosisContextManager.schema_hash(result.next_step.schema_),
                            resolved_arguments=resolution.arguments,
                            required_missing=resolution.missing_required,
                            auto_step_count=current_auto,
                            reason=resolution.question_reason or "parameter_confirmation_required",
                        )
                        metadata.update({"required": resolution.missing_required, "missing_required": resolution.missing_required, "resolved_arguments": resolution.arguments, "pending_id": pending_id})
                        DiagnosisContextManager.set_pending(context, pending)
                        self.session_store.update_diagnosis_context(context)
                        return AgentResult(
                            status="suspended",
                            evidence_ids=evidence_ids,
                            requirement=self._build_suspension_requirement(
                                resolution.missing_required,
                                result.next_step.tool_name,
                                context,
                                metadata,
                            ),
                        )
                    current_tool = result.next_step.tool_name
                    current_args = resolution.arguments
                    current_auto += 1
                    continue

                if decision.action == "require_user_input" and decision.pending_input:
                    pending_id = f"pin_{uuid.uuid4().hex}"
                    pending = PendingStepState(
                        pending_id=pending_id,
                        resume_action=decision.pending_input.metadata.get("resume_action", "continue_mcp_with_args"),
                        auto_step_count=current_auto,
                        reason=decision.reason,
                    )
                    DiagnosisContextManager.set_pending(context, pending)
                    self.session_store.update_diagnosis_context(context)
                    return AgentResult(
                        status="suspended",
                        evidence_ids=evidence_ids,
                        requirement=AgentRequirement(
                            input_type=decision.pending_input.input_type,
                            question=decision.pending_input.question,
                            options=[{"label": o.label, "value": o.value, "description": o.description} for o in decision.pending_input.options],
                            metadata={
                                **decision.pending_input.metadata,
                                "agent_type": "diagnosis",
                                "diagnosis_id": context.diagnosis_id,
                                "context_revision": context.revision,
                                "pending_id": pending_id,
                                "auto_step_count": current_auto,
                            },
                        ),
                    )
                return AgentResult(status="completed", evidence_ids=evidence_ids)

            return AgentResult(status="completed", evidence_ids=evidence_ids)
        except Exception as exc:
            self.session_store.update_diagnosis_context(context)
            return AgentResult(status="failed", error_msg=str(exc), evidence_ids=evidence_ids)

    def _extract_produced_params(self, raw: Any, text: str = "") -> Dict[str, Any]:
        """Best-effort extraction of MCP structured produced parameters."""
        extracted = {}
        if isinstance(raw, dict):
            candidates = [raw]
            for key in ("parsedContent", "structuredContent", "structured_content", "result"):
                value = raw.get(key)
                if isinstance(value, dict):
                    candidates.append(value)
            for candidate in candidates:
                for key in ("produced_params", "outputs", "context_updates"):
                    value = candidate.get(key)
                    if isinstance(value, dict):
                        extracted.update({k: v for k, v in value.items() if v not in (None, "")})
                        break
        
        if text:
            import re
            import json
            blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
            for block in blocks:
                try:
                    parsed = json.loads(block)
                    if isinstance(parsed, dict) and "properties" not in parsed and "type" not in parsed:
                        for k, v in parsed.items():
                            if v not in (None, ""):
                                extracted[k] = v
                except Exception:
                    pass
        return extracted

    def _save_search_evidence(self, session_id: str, plan_step_id: str, goal: str, search_query: str, search: Any, playbook_selection: dict) -> str:
        """
        Saves the results of an MCP playbook search as evidence.

        Args:
            session_id: The ID of the current session.
            plan_step_id: The ID of the current plan step.
            goal: The original user goal/message.
            search_query: The rewritten query used for searching.
            search: The search results from the MCP gateway.
            playbook_selection: The LLM's playbook selection metadata.

        Returns:
            The ID of the created evidence.
        """
        evidence = self.session_store.create_evidence(CreateEvidenceRequest(
            session_id=session_id,
            step_id=plan_step_id,
            type=EvidenceType.MCP_OBSERVATION,
            source="msinsight_mcp",
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
                "original_query": goal,
                "search_query": search_query,
                "llm_playbook_selection": playbook_selection,
            },
        ))
        return evidence.id

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
        """
        Resolves arguments for an MCP tool by merging suggested arguments with context information.

        Args:
            step: The next step definition containing the tool's schema.
            suggested: Arguments suggested by the MCP server or LLM.
            context: Additional context information (e.g., extracted path).

        Returns:
            A dictionary of resolved arguments.
        """
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

    def _missing_required_arguments(self, step: Optional[MCPNextStep], arguments: Dict[str, Any]) -> List[str]:
        """
        Identifies required arguments that are missing from the provided arguments dictionary.

        Args:
            step: The next step definition containing the tool's schema.
            arguments: The arguments to check.

        Returns:
            A list of missing required argument names.
        """
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
        """
        Parses user input into a dictionary of arguments.

        Args:
            user_input: The input provided by the user (can be a string, dict, or other type).

        Returns:
            A dictionary representation of the user input.
        """
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

