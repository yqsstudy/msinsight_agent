"""Controlled LLM assistance for MCP playbook orchestration."""

import asyncio
import json
from typing import Any, Dict, List, Optional

from ..llm import LLMRouter
from ..models.config import LLMAssistanceConfig
from ..models.orchestration import (
    LLMEvidenceSummaryResult,
    LLMParameterExtractionResult,
    LLMPlaybookRecommendationResult,
    LLMPlaybookSelectionResult,
    LLMQueryRewriteResult,
    MCPNextStep,
)
from ..observability import get_logger

logger = get_logger(__name__)


class MCPLLMOrchestrationAssistant:
    """Advisory LLM helper that never executes or invents MCP tools."""

    def __init__(self, llm_router: Optional[LLMRouter] = None, config: Optional[LLMAssistanceConfig] = None):
        self.llm_router = llm_router
        self.config = config or LLMAssistanceConfig()

    async def rewrite_query(self, user_text: str, context: Optional[Dict[str, Any]] = None) -> str:
        if not self._enabled("query_rewrite"):
            return user_text
        payload = await self._chat_json(
            "query_rewrite",
            [
                {"role": "system", "content": "Rewrite the user request into a concise profiler playbook search query. Return only JSON with rewritten_query and optional rationale. Do not add facts not present in the input."},
                {"role": "user", "content": json.dumps({"user_text": user_text, "context": context or {}}, ensure_ascii=False)},
            ],
        )
        if not payload:
            return user_text
        try:
            result = LLMQueryRewriteResult(**payload)
        except Exception as exc:
            logger.warning(f"LLM query rewrite validation failed: {exc}")
            return user_text
        rewritten = result.rewritten_query.strip()
        if not rewritten or len(rewritten) > 500:
            return user_text
        return rewritten

    async def select_playbook_from_tools(
        self,
        user_text: str,
        tools: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not tools or not self._enabled("candidate_recommendation"):
            return {}
        profiler_tool = next((tool for tool in tools if tool.get("name") == "search_profiler_tools"), None)
        if not profiler_tool:
            return {}
        payload = await self._chat_json(
            "playbook_selection",
            [
                {"role": "system", "content": "Decide whether the user request clearly matches one playbook advertised by the search_profiler_tools MCP tool description. Return only JSON: {\"select_playbook\": string|null, \"query\": string|null, \"confidence\": 0-1, \"reason\": string}. Only select a playbook ID explicitly present in the provided tool metadata or description. If the request is ambiguous, use null. Do not invent playbooks or internal tool names."},
                {"role": "user", "content": json.dumps({"user_text": user_text, "context": context or {}, "tool": profiler_tool}, ensure_ascii=False)},
            ],
        )
        if not payload:
            return {}
        try:
            result = LLMPlaybookSelectionResult(**payload)
        except Exception as exc:
            logger.warning(f"LLM playbook selection validation failed: {exc}")
            return {}
        if not result.select_playbook or result.confidence < 0.8:
            return {}
        tool_text = json.dumps(profiler_tool, ensure_ascii=False)
        if result.select_playbook not in tool_text:
            return {}
        selection = {"select_playbook": result.select_playbook, "confidence": result.confidence, "reason": result.reason}
        if result.query and result.query.strip() and len(result.query.strip()) <= 500:
            selection["query"] = result.query.strip()
        return selection

    async def recommend_playbook_candidate(
        self,
        user_text: str,
        candidates: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not candidates or not self._enabled("candidate_recommendation"):
            return candidates
        limited = candidates[: self.config.max_candidates]
        candidate_ids = [self._candidate_id(candidate) for candidate in limited]
        payload = await self._chat_json(
            "candidate_recommendation",
            [
                {"role": "system", "content": "Rank only the provided playbook candidates for the user request. Return only JSON: {\"recommendations\":[{\"playbook_id\":...,\"confidence\":0-1,\"reason\":...}]}. Do not create new playbooks."},
                {"role": "user", "content": json.dumps({"user_text": user_text, "context": context or {}, "candidates": limited}, ensure_ascii=False)},
            ],
        )
        if not payload:
            return candidates
        try:
            result = LLMPlaybookRecommendationResult(**payload)
        except Exception as exc:
            logger.warning(f"LLM candidate recommendation validation failed: {exc}")
            return candidates

        by_id = {candidate_id: candidate for candidate_id, candidate in zip(candidate_ids, limited) if candidate_id}
        ranked: List[Dict[str, Any]] = []
        seen = set()
        for recommendation in result.recommendations:
            candidate = by_id.get(recommendation.playbook_id)
            if not candidate or recommendation.playbook_id in seen:
                continue
            enriched = dict(candidate)
            enriched["llm_recommendation_reason"] = recommendation.reason
            enriched["llm_confidence"] = recommendation.confidence
            ranked.append(enriched)
            seen.add(recommendation.playbook_id)
        if not ranked:
            return candidates
        ranked.extend(candidate for candidate_id, candidate in zip(candidate_ids, limited) if candidate_id not in seen)
        ranked.extend(candidates[len(limited):])
        return ranked

    async def extract_parameters(
        self,
        user_text: str,
        step: Optional[MCPNextStep],
        existing_params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not step or not step.schema_ or not self._enabled("parameter_extraction"):
            return existing_params
        allowed = self._allowed_parameter_names(step)
        if not allowed:
            return existing_params
        payload = await self._chat_json(
            "parameter_extraction",
            [
                {"role": "system", "content": "Extract only parameters explicitly stated or strongly implied by the user text for the provided JSON schema. Return only JSON with parameters, missing_required, confidence. Do not invent file paths, snapshot ids, ranks, or domains."},
                {"role": "user", "content": json.dumps({"user_text": user_text, "context": context or {}, "schema": step.schema_, "existing_params": existing_params}, ensure_ascii=False)},
            ],
        )
        if not payload:
            return existing_params
        try:
            result = LLMParameterExtractionResult(**payload)
        except Exception as exc:
            logger.warning(f"LLM parameter extraction validation failed: {exc}")
            return existing_params
        merged = dict(existing_params)
        for key, value in result.parameters.items():
            if key in allowed and key not in merged and value not in (None, ""):
                merged[key] = value
        return merged

    async def enhance_summary(self, deterministic_summary: str, evidence: Dict[str, Any]) -> str:
        if not deterministic_summary or not self._enabled("summary_enhancement"):
            return deterministic_summary
        compact = json.dumps(evidence, ensure_ascii=False)[: self.config.max_evidence_chars]
        payload = await self._chat_json(
            "summary_enhancement",
            [
                {"role": "system", "content": "Rewrite the summary using only the supplied evidence. Return only JSON with summary and caveats. Do not introduce new diagnoses, metrics, tools, or recommendations."},
                {"role": "user", "content": json.dumps({"deterministic_summary": deterministic_summary, "evidence": compact}, ensure_ascii=False)},
            ],
        )
        if not payload:
            return deterministic_summary
        try:
            result = LLMEvidenceSummaryResult(**payload)
        except Exception as exc:
            logger.warning(f"LLM summary enhancement validation failed: {exc}")
            return deterministic_summary
        summary = result.summary.strip()
        return summary or deterministic_summary

    async def _chat_json(self, stage: str, messages: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        if not self.llm_router:
            return None
        try:
            response = await asyncio.wait_for(
                self.llm_router.chat(messages=messages, temperature=0.1),
                timeout=self.config.timeout_seconds,
            )
            content = response.get("content", "") if isinstance(response, dict) else str(response)
            parsed = self._parse_json_object(content)
            if not isinstance(parsed, dict):
                return None
            return parsed
        except Exception as exc:
            logger.warning(f"LLM assistance failed at {stage}: {type(exc).__name__}: {exc}")
            return None

    def _enabled(self, stage: str) -> bool:
        if not self.config.enabled:
            return False
        return {
            "query_rewrite": self.config.query_rewrite_enabled,
            "candidate_recommendation": self.config.candidate_recommendation_enabled,
            "parameter_extraction": self.config.parameter_extraction_enabled,
            "summary_enhancement": self.config.summary_enhancement_enabled,
        }.get(stage, False)

    def _parse_json_object(self, content: str) -> Optional[Dict[str, Any]]:
        text = (content or "").strip()
        if not text:
            return None
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                value = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
            return value if isinstance(value, dict) else None

    def _candidate_id(self, candidate: Dict[str, Any]) -> Optional[str]:
        value = candidate.get("id") or candidate.get("playbook_id") or candidate.get("playbookId") or candidate.get("name")
        return str(value) if value else None

    def _allowed_parameter_names(self, step: MCPNextStep) -> set[str]:
        properties = step.schema_.get("properties", {}) if step.schema_ else {}
        return set(properties.keys()) if isinstance(properties, dict) else set()
