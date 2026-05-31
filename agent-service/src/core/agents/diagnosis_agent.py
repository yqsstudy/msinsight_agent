import uuid
from typing import Any, List, Optional, Dict
from .base import BaseWorkerAgent, AgentResult, AgentRequirement
from ...models.orchestration import PendingInputOption, MCPSearchResult, MCPNextStep
from ...models.evidence import CreateEvidenceRequest, EvidenceType, EvidenceConfidence, MCPObservationMetadata

class DiagnosisAgent(BaseWorkerAgent):
    """Agent specialized in diagnostic tasks, leveraging MCP tools and playbooks."""

    def __init__(self, mcp_gateway, session_store, policy, llm_assistant):
        self.mcp_gateway = mcp_gateway
        self.session_store = session_store
        self.policy = policy
        self.llm_assistant = llm_assistant

    async def run(self, session_id: str, plan_step_id: str, goal: str, blackboard: dict) -> AgentResult:
        """Initial diagnostic execution: search playbooks and start chain."""
        extracted = blackboard.get("extracted", {})
        
        try:
            # 1. Load tools and let LLM help select/rewrite
            tools = await self.mcp_gateway.ensure_tools_loaded()
            playbook_selection = await self.llm_assistant.select_playbook_from_tools(goal, tools, {"extracted": extracted})
            search_query = playbook_selection.get("query") or await self.llm_assistant.rewrite_query(goal, {"extracted": extracted})
            selected_playbook = extracted.get("selected_playbook") or playbook_selection.get("select_playbook")
            
            # --- Try to extract common parameters early based on the goal ---
            # If the user provides a path in the initial query, we extract it.
            # E.g., "帮我看看 /path/to/file 是否存在问题"
            import re
            early_path_match = re.search(r'([a-zA-Z]:\\[^\s"\'<>]+|/[^\s"\'<>]+)', goal)
            if early_path_match and not extracted.get("path"):
                extracted["path"] = early_path_match.group(1).strip()
            
            # 2. Search MCP playbooks
            search = await self.mcp_gateway.search_profiler_tools(search_query, selected_playbook)
            
            # 3. Use LLM to recommend/confirm candidate
            search.playbook_candidates = await self.llm_assistant.recommend_playbook_candidate(
                goal,
                search.playbook_candidates,
                {"extracted": extracted, "search_query": search_query},
            )
            
            # 4. Save search evidence
            evidence_id = self._save_search_evidence(session_id, plan_step_id, goal, search_query, search, playbook_selection)
            
            # 5. Handle user choice if required
            if search.requires_user_choice:
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
                                "description": str(c.get("description") or "")
                            } for c in search.playbook_candidates
                        ],
                        metadata={
                            "agent_type": "diagnosis",
                            "resume_action": "select_playbook",
                            "original_message": goal,
                            "candidates": search.playbook_candidates,
                            "context": {"extracted": extracted}
                        }
                    )
                )

            # 6. Check for initial step and missing params
            if not search.initial_step or not search.initial_step.tool_name:
                return AgentResult(
                    status="suspended",
                    evidence_ids=[evidence_id],
                    requirement=AgentRequirement(
                        input_type="text",
                        question="MCP 已返回剧本搜索结果，但未提供可执行的首个步骤。请补充要执行的 profiler 工具或调整问题描述。",
                        metadata={
                            "agent_type": "diagnosis",
                            "resume_action": "select_playbook",
                            "original_message": goal
                        }
                    )
                )

            # Resolve arguments for the first step
            initial_step = search.initial_step
            resolved_args = self._resolve_step_arguments(initial_step, search.suggested_arguments, {"message": goal, **extracted})
            resolved_args = await self.llm_assistant.extract_parameters(goal, initial_step, resolved_args, {"message": goal, **extracted})
            
            missing = self._missing_required_arguments(initial_step, resolved_args)
            if missing:
                return AgentResult(
                    status="suspended",
                    evidence_ids=[evidence_id],
                    requirement=AgentRequirement(
                        input_type="params",
                        question=f"MCP 首步 `{initial_step.tool_name}` 需要参数：{', '.join(missing)}。请补充参数。",
                        metadata={
                            "agent_type": "diagnosis",
                            "resume_action": "continue_mcp_with_args",
                            "tool_name": initial_step.tool_name,
                            "required": missing,
                            "resolved_arguments": resolved_args,
                            "tool_schema": initial_step.schema_,
                            "context": {"message": goal, "path": extracted.get("path"), "selected_playbook": search.selected_playbook or search.auto_selected_playbook}
                        }
                    )
                )

            # 7. Start the MCP execution chain
            context = {
                "message": goal,
                "path": extracted.get("path"),
                "selected_playbook": search.selected_playbook or search.auto_selected_playbook,
            }
            # We don't stream here, just run the chain and collect evidence
            # In a real streaming scenario, we'd need to yield events, 
            # but BaseWorkerAgent.run is a single call. 
            # We'll rely on the Orchestrator to handle SSE if we were to refactor further.
            # For now, we perform one execution and return.
            
            # NOTE: To support multi-step auto-execution within a single 'run', 
            # we would loop here. For simplicity and following the 'signal' pattern,
            # we'll execute the first tool and return its result/next_step.
            
            chain_result = await self._execute_tool_and_check_next(session_id, plan_step_id, initial_step.tool_name, resolved_args, 0, context)
            chain_result.evidence_ids.append(evidence_id)
            return chain_result

        except Exception as exc:
            return AgentResult(status="failed", error_msg=str(exc))

    def _is_complex_sentence(self, text: str) -> bool:
        """Heuristic to determine if input is a conversational sentence rather than a raw value."""
        return len(text) > 20 or any(char in text for char in ["，", "。", "！", "？", "帮我", "请", "是什么"])

    async def resume(self, session_id: str, plan_step_id: str, user_input: Any, suspended_metadata: dict) -> AgentResult:
        """Resume execution from a suspended state."""
        resume_action = suspended_metadata.get("resume_action")
        context = suspended_metadata.get("context", {})
        
        if resume_action == "select_playbook":
            # Restart run with the selected playbook merged into context
            blackboard = {
                "extracted": {
                    **context.get("extracted", {}),
                    "selected_playbook": str(user_input).strip()
                }
            }
            return await self.run(session_id, plan_step_id, suspended_metadata.get("original_message", ""), blackboard)
            
        if resume_action == "continue_mcp_with_args":
            tool_name = suspended_metadata.get("tool_name")
            resolved = suspended_metadata.get("resolved_arguments", {})
            required_missing = suspended_metadata.get("required", [])
            tool_schema = suspended_metadata.get("tool_schema", {})
            
            new_args = {}
            
            # --- FUNNEL 0: Structured Input (Dict or JSON) ---
            parsed_args = self._parse_user_arguments(user_input)
            if isinstance(user_input, dict) or (isinstance(user_input, str) and "value" not in parsed_args):
                new_args = parsed_args

            # --- FUNNEL 1: Fast Path (Single missing param, simple input) ---
            if not new_args and isinstance(user_input, str) and len(required_missing) == 1 and not self._is_complex_sentence(user_input):
                 new_args[required_missing[0]] = user_input.strip()
                 
            # --- FUNNEL 2: Deep Path (LLM Schema Extraction) ---
            if not new_args:
                 new_args = await self.llm_assistant.extract_parameters_by_schema(
                     user_input=str(user_input),
                     tool_schema=tool_schema,
                     existing_args=resolved
                 )
                 
            # Merge and execute
            merged_args = {**resolved, **new_args}
            
            # Clean arguments using schema properties
            allowed_keys = set(tool_schema.get("properties", {}).keys())
            allowed_keys.update({"file_path", "project_name"}) 
            clean_args = {k: v for k, v in merged_args.items() if k in allowed_keys}
            
            auto_count = int(suspended_metadata.get("auto_step_count", 0))
            return await self._execute_tool_and_check_next(session_id, plan_step_id, tool_name, clean_args, auto_count, context)

        return AgentResult(status="failed", error_msg=f"Unknown resume action: {resume_action}")

    async def _execute_tool_and_check_next(self, session_id: str, plan_step_id: str, tool_name: str, arguments: dict, auto_count: int, context: dict) -> AgentResult:
        """Executes a single tool and decides whether to continue, stop, or suspend."""
        try:
            result = await self.mcp_gateway.execute_profiler_tool(tool_name, arguments)
            
            # Manually check for soft errors returned as success by the MCP server handler
            text = result.text.strip() if result.text else ""
            if text.startswith("ERROR:") or "EXECUTION BLOCKED:" in text:
                return AgentResult(status="failed", error_msg=text)
                
            # Save evidence
            metadata = MCPObservationMetadata(
                mcp_tool="execute_profiler_tool",
                internal_tool=tool_name,
                arguments=arguments,
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
                summary=f"MCP 工具 `{tool_name}` 执行结果",
                confidence=EvidenceConfidence.MEDIUM,
                metadata=metadata.model_dump(),
            ))
            
            decision = self.policy.decide_after_mcp_result(session_id, result, auto_count)
            
            if decision.action == "continue_auto" and result.next_step and result.next_step.tool_name:
                next_step = result.next_step
                next_args = self._resolve_step_arguments(next_step, {}, context)
                next_args = await self.llm_assistant.extract_parameters(context.get("message", ""), next_step, next_args, context)
                
                missing = self._missing_required_arguments(next_step, next_args)
                if missing:
                    return AgentResult(
                        status="suspended",
                        evidence_ids=[evidence.id],
                        requirement=AgentRequirement(
                            input_type="params",
                            question=f"下一步 `{next_step.tool_name}` 需要参数：{', '.join(missing)}。请补充参数。",
                            metadata={
                                "agent_type": "diagnosis",
                                "resume_action": "continue_mcp_with_args",
                                "tool_name": next_step.tool_name,
                                "required": missing,
                                "resolved_arguments": next_args,
                                "tool_schema": next_step.schema_,
                                "context": context,
                                "auto_step_count": auto_count
                            }
                        )
                    )
                
                # Clean arguments using schema properties
                allowed_keys = set(next_step.schema_.get("properties", {}).keys())
                allowed_keys.update({"file_path", "project_name"}) 
                clean_next_args = {k: v for k, v in next_args.items() if k in allowed_keys}

                # Recursive call for auto-continuation (be careful with recursion depth, though policy handles auto_count)
                res = await self._execute_tool_and_check_next(session_id, plan_step_id, next_step.tool_name, clean_next_args, auto_count + 1, context)
                res.evidence_ids.append(evidence.id)
                return res
            
            if decision.action == "require_user_input" and decision.pending_input:
                # Map Orchestrator's PendingInput to AgentRequirement
                return AgentResult(
                    status="suspended",
                    evidence_ids=[evidence.id],
                    requirement=AgentRequirement(
                        input_type=decision.pending_input.input_type,
                        question=decision.pending_input.question,
                        options=[{"label": o.label, "value": o.value, "description": o.description} for o in decision.pending_input.options],
                        metadata={
                            **decision.pending_input.metadata,
                            "agent_type": "diagnosis",
                            "context": context,
                            "auto_step_count": auto_count
                        }
                    )
                )

            return AgentResult(status="completed", evidence_ids=[evidence.id])

        except Exception as exc:
            return AgentResult(status="failed", error_msg=str(exc))

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

