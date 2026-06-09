"""Schema-aware parameter resolution for MCP diagnosis steps."""

from __future__ import annotations

import inspect
import json
from typing import Any, Dict, Optional

from ...models.orchestration import MCPNextStep
from .compact import compact_for_llm
from .models import (
    ConfidenceLevel,
    ConflictSeverity,
    DiagnosisContext,
    ParamSource,
    ParameterConflict,
    ParameterResolutionResult,
    ResolvedParameter,
)


PATH_ALIASES = {"path", "file_path", "filepath", "trace_path", "trace_file", "data_path", "db_path"}
QUERY_ALIASES = {"query", "question", "user_query", "goal", "message"}


class ParameterResolver:
    """Resolve MCP tool arguments from effective diagnosis context.

    LLM assistance is advisory only. This resolver owns schema filtering,
    provenance-aware conflict detection, and missing-required decisions.
    """

    def __init__(self, llm_assistant: Any | None = None):
        self.llm_assistant = llm_assistant

    async def resolve_for_step(
        self,
        context: DiagnosisContext,
        step: Optional[MCPNextStep],
        suggested_args: Optional[Dict[str, Any]] = None,
        current_user_input: Any = None,
        existing_args: Optional[Dict[str, Any]] = None,
        previous_missing: Optional[list[str]] = None,
    ) -> ParameterResolutionResult:
        properties = self._schema_properties(step)
        allowed = set(properties.keys())
        required = self._required(step)
        arguments: Dict[str, Any] = {}
        filled: list[ResolvedParameter] = []
        conflicts: list[ParameterConflict] = []
        param_sources: Dict[str, Any] = {}

        def apply(key: str, value: Any, source: ParamSource | str, confidence: ConfidenceLevel | str, explicit: bool = False) -> None:
            if not self._is_present(value):
                return
            if allowed and key not in allowed:
                return
            if key in arguments and arguments[key] != value:
                conflicts.append(self._conflict(context, key, arguments[key], value, source, explicit=explicit))
                if explicit:
                    arguments[key] = value
                    self._replace_filled(filled, key, value, source, confidence)
                    param_sources[key] = self._param_source_entry(key, value, source, confidence)
                return
            if key not in arguments:
                arguments[key] = value
                filled.append(ResolvedParameter(key=key, value=value, source=source, confidence=confidence))
                param_sources[key] = self._param_source_entry(key, value, source, confidence)

        for key, value in (suggested_args or {}).items():
            apply(key, value, ParamSource.MCP_SUGGESTED_ARGUMENT, ConfidenceLevel.MEDIUM)
        for key, value in (existing_args or {}).items():
            apply(key, value, "existing_arg", ConfidenceLevel.HIGH)

        explicit_args = self._parse_user_arguments(current_user_input)
        
        # Only map raw free-text `value` to arbitrary fields during resume, when
        # the previous pending-input state tells us exactly which field was missing.
        currently_missing = previous_missing or []

        for key, value in explicit_args.items():
            if key.lower() == "value" and previous_missing and isinstance(value, str) and self._is_complex_sentence(value):
                continue
            mapped_key = self._map_alias_to_schema_key(key, allowed, currently_missing)
            if mapped_key:
                provenance = context.param_provenance.get(mapped_key)
                if provenance and not provenance.invalidated and context.known_params.get(mapped_key) != value:
                    conflicts.append(self._conflict(context, mapped_key, context.known_params.get(mapped_key), value, ParamSource.USER_RESUME, explicit=True))
                apply(mapped_key, value, ParamSource.USER_RESUME, ConfidenceLevel.HIGH, explicit=True)

        for key, value in context.known_params.items():
            provenance = context.param_provenance.get(key)
            if provenance and provenance.invalidated:
                continue
            mapped_key = self._map_context_key_to_schema_key(key, allowed)
            if mapped_key:
                apply(mapped_key, value, provenance.source if provenance else ParamSource.TRANSFERRED, provenance.confidence if provenance else ConfidenceLevel.MEDIUM)

        for key, value in self._latest_step_output_params(context).items():
            mapped_key = self._map_context_key_to_schema_key(key, allowed)
            if mapped_key:
                apply(mapped_key, value, ParamSource.MCP_OUTPUT, ConfidenceLevel.HIGH)

        for key in allowed:
            lowered = key.lower()
            if lowered in QUERY_ALIASES:
                apply(key, context.latest_user_input or context.root_message, ParamSource.USER_INITIAL, ConfidenceLevel.HIGH)
            elif lowered in PATH_ALIASES:
                path = self._first_known_path(context)
                if path:
                    apply(key, path, ParamSource.TRANSFERRED, ConfidenceLevel.HIGH)

        missing_before_llm = [key for key in (previous_missing or required) if not self._is_present(arguments.get(key))]
        should_use_llm = bool(missing_before_llm) or (isinstance(current_user_input, str) and self._is_complex_sentence(current_user_input))
        if self.llm_assistant and should_use_llm:
            llm_args = await self.llm_assistant.extract_parameters_by_schema(
                user_input=str(current_user_input or context.latest_user_input or context.root_message),
                tool_schema=step.schema_ if step else {},
                existing_args=arguments,
                context={
                    **compact_for_llm(context, stage="parameter_resolution"),
                    "tool_name": step.tool_name if step else None,
                },
            )
            if inspect.isawaitable(llm_args):
                llm_args = await llm_args
            if not isinstance(llm_args, dict):
                llm_args = {}
            if not llm_args and hasattr(self.llm_assistant, "extract_parameters"):
                fallback_args = await self.llm_assistant.extract_parameters(
                    str(current_user_input or context.latest_user_input or context.root_message),
                    step,
                    arguments,
                    compact_for_llm(context, stage="parameter_resolution"),
                )
                if inspect.isawaitable(fallback_args):
                    fallback_args = await fallback_args
                if isinstance(fallback_args, dict):
                    llm_args = fallback_args
            for key, value in (llm_args or {}).items():
                if key not in allowed:
                    continue
                provenance = context.param_provenance.get(key)
                if key in arguments and arguments[key] != value:
                    confidence = provenance.confidence if provenance else ConfidenceLevel.MEDIUM
                    conflicts.append(self._conflict(context, key, arguments[key], value, ParamSource.LLM_EXTRACTION, explicit=False))
                    if confidence == ConfidenceLevel.HIGH:
                        continue
                apply(key, value, ParamSource.LLM_EXTRACTION, ConfidenceLevel.LOW)

        llm_assistance = {}
        if self.llm_assistant and hasattr(self.llm_assistant, "last_failure_summary"):
            llm_assistance = self.llm_assistant.last_failure_summary()

        clean_arguments = self._filter_by_schema(arguments, properties)
        missing = [key for key in required if not self._is_present(clean_arguments.get(key))]
        needs_confirmation = any(str(conflict.severity).split(".")[-1].lower() in {"requires_invalidation"} for conflict in conflicts)
        question_reason = None
        if conflicts:
            question_reason = "parameter_conflict"
        elif missing:
            question_reason = "missing_required_arguments"

        clean_param_sources = {key: value for key, value in param_sources.items() if key in clean_arguments}
        return ParameterResolutionResult(
            arguments=clean_arguments,
            missing_required=missing,
            filled=filled,
            conflicts=conflicts,
            needs_confirmation=needs_confirmation,
            question_reason=question_reason,
            param_sources=clean_param_sources,
            llm_assistance=llm_assistance if isinstance(llm_assistance, dict) else {},
            metadata={"required": required},
        )

    def _schema_properties(self, step: Optional[MCPNextStep]) -> Dict[str, Any]:
        if not step or not step.schema_:
            return {}
        properties = step.schema_.get("properties", {})
        return properties if isinstance(properties, dict) else {}

    def _required(self, step: Optional[MCPNextStep]) -> list[str]:
        if not step or not step.schema_:
            return []
        required = step.schema_.get("required", [])
        return [str(item) for item in required] if isinstance(required, list) else []

    def _filter_by_schema(self, arguments: Dict[str, Any], properties: Dict[str, Any]) -> Dict[str, Any]:
        if not properties:
            return dict(arguments)
        return {key: value for key, value in arguments.items() if key in properties}

    def _is_present(self, value: Any) -> bool:
        return value is not None and value != ""

    def _parse_user_arguments(self, user_input: Any) -> Dict[str, Any]:
        if user_input is None:
            return {}
        if isinstance(user_input, dict):
            return user_input
        if not isinstance(user_input, str):
            return {"value": user_input}
        text = user_input.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"value": text}
        return parsed if isinstance(parsed, dict) else {"value": text}

    def _is_complex_sentence(self, text: str) -> bool:
        return len(text) > 20 or any(marker in text for marker in ["，", "。", "！", "？", "帮我", "请", "查一下", "是什么"])

    def _map_alias_to_schema_key(self, key: str, allowed: set[str], currently_missing: Optional[list[str]] = None) -> Optional[str]:
        if key in allowed:
            return key
        lowered = key.lower()
        for candidate in allowed:
            if candidate.lower() == lowered:
                return candidate
        if lowered == "value":
            if currently_missing and len(currently_missing) == 1:
                return currently_missing[0]
            if len(allowed) == 1:
                only = next(iter(allowed))
                if only.lower() in PATH_ALIASES or only.lower() in QUERY_ALIASES:
                    return only
            return None
        if lowered in PATH_ALIASES:
            return self._first_allowed_alias(allowed, PATH_ALIASES)
        if lowered in QUERY_ALIASES:
            return self._first_allowed_alias(allowed, QUERY_ALIASES)
        return None

    def _map_context_key_to_schema_key(self, key: str, allowed: set[str]) -> Optional[str]:
        mapped = self._map_alias_to_schema_key(key, allowed)
        if mapped:
            return mapped
        lowered = key.lower()
        if lowered in PATH_ALIASES:
            return self._first_allowed_alias(allowed, PATH_ALIASES)
        if lowered in QUERY_ALIASES:
            return self._first_allowed_alias(allowed, QUERY_ALIASES)
        return None

    def _first_allowed_alias(self, allowed: set[str], aliases: set[str]) -> Optional[str]:
        for candidate in allowed:
            if candidate.lower() in aliases:
                return candidate
        return None

    def _first_known_path(self, context: DiagnosisContext) -> Any:
        for key, value in context.known_params.items():
            if key.lower() in PATH_ALIASES and self._is_present(value):
                provenance = context.param_provenance.get(key)
                if provenance and provenance.invalidated:
                    continue
                return value
        return None

    def _latest_step_output_params(self, context: DiagnosisContext) -> Dict[str, Any]:
        if not context.completed_steps:
            return {}
        latest = context.completed_steps[-1]
        output = latest.result_summary.get("produced_params")
        return output if isinstance(output, dict) else {}

    def _param_source_entry(self, key: str, value: Any, source: ParamSource | str, confidence: ConfidenceLevel | str) -> Dict[str, Any]:
        source_value = getattr(source, "value", source)
        confidence_value = getattr(confidence, "value", confidence)
        label = self._display_label(key)
        display = f"{label} 已解析：{value}"
        if source_value in {ParamSource.USER_RESUME.value, "user_input", "user_resume"}:
            display = f"{label} 来自本次输入：{value}"
        elif source_value in {ParamSource.MCP_OUTPUT.value, "previous_step_output"}:
            display = f"{label} 已沿用上一步结果：{value}"
        elif source_value in {ParamSource.TRANSFERRED.value, "existing_arg", "previous_step_args"}:
            display = f"{label} 已沿用上下文：{value}"
        return {
            "value": value,
            "source": source_value,
            "display": display,
            "confidence": confidence_value,
        }

    def _display_label(self, key: str) -> str:
        return {
            "iterationId": "迭代 ID",
            "groupIdHash": "通信组",
        }.get(key, key)

    def _replace_filled(self, filled: list[ResolvedParameter], key: str, value: Any, source: ParamSource | str, confidence: ConfidenceLevel | str) -> None:
        filled[:] = [item for item in filled if item.key != key]
        filled.append(ResolvedParameter(key=key, value=value, source=source, confidence=confidence, user_confirmed=True))

    def _conflict(self, context: DiagnosisContext, key: str, existing_value: Any, new_value: Any, new_source: ParamSource | str, explicit: bool) -> ParameterConflict:
        provenance = context.param_provenance.get(key)
        severity = ConflictSeverity.REQUIRES_CONFIRMATION
        affected_step_index = provenance.source_step_index if provenance else None
        if explicit and affected_step_index is not None:
            severity = ConflictSeverity.REQUIRES_INVALIDATION
        elif explicit:
            severity = ConflictSeverity.WARNING
        return ParameterConflict(
            key=key,
            existing_value=existing_value,
            new_value=new_value,
            existing_source=provenance.source if provenance else None,
            new_source=new_source,
            severity=severity,
            affected_step_index=affected_step_index,
            reason="explicit user value conflicts with effective context" if explicit else "advisory extraction conflicts with effective context",
        )
