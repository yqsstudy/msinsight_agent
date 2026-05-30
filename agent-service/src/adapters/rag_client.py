"""MS-RAG HTTP adapter."""

import time
from typing import Any, Dict, Optional

import httpx

from ..models.config import RAGConfig
from ..models.orchestration import RAGRetrieveItem, RAGRetrieveResult
from ..observability import get_logger

logger = get_logger(__name__)


class RAGClient:
    """Client for MS-RAG service."""

    def __init__(self, config: Optional[RAGConfig] = None):
        self.config = config or RAGConfig()

    async def retrieve(self, query: str, top_k: Optional[int] = None) -> RAGRetrieveResult:
        start = time.time()
        url = self.config.base_url.rstrip("/") + self.config.retrieve_path
        payload = {"query": query, "top_k": top_k or self.config.top_k}
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                raw = response.json()
        except Exception as exc:
            logger.error(f"RAG retrieve failed: {exc}")
            raise RuntimeError(f"RAG_UNAVAILABLE: {exc}") from exc

        elapsed_ms = int((time.time() - start) * 1000)
        data = raw.get("data", raw)
        raw_results = data.get("results", []) if isinstance(data, dict) else []
        items = [self._normalize_result(item) for item in raw_results]
        return RAGRetrieveResult(query=query, results=items, elapsed_ms=elapsed_ms, raw=raw)

    async def qa(self, query: str, top_k: Optional[int] = None) -> Dict[str, Any]:
        url = self.config.base_url.rstrip("/") + self.config.qa_path
        payload = {"query": query, "options": {"top_k": top_k or self.config.top_k}}
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            logger.error(f"RAG qa failed: {exc}")
            raise RuntimeError(f"RAG_UNAVAILABLE: {exc}") from exc

    async def health(self) -> Dict[str, Any]:
        url = self.config.base_url.rstrip("/") + "/api/v1/health"
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc)}

    def _normalize_result(self, item: Dict[str, Any]) -> RAGRetrieveItem:
        source = item.get("source") or item.get("metadata", {}).get("source") or {}
        if isinstance(source, str):
            source = {"path": source}
        source = {
            **source,
            "doc_id": source.get("doc_id") or item.get("doc_id"),
            "chunk_id": source.get("chunk_id") or item.get("chunk_id"),
            "title": source.get("title") or item.get("doc_title") or item.get("title"),
            "section_title": source.get("section_title") or item.get("section_title"),
            "path": source.get("path") or item.get("path") or item.get("file_path") or item.get("source_url"),
            "url": source.get("url") or item.get("source_url"),
        }
        content = item.get("content") or item.get("text") or item.get("document") or ""
        score = item.get("score") or item.get("similarity") or item.get("final_score")
        metadata = {
            **(item.get("metadata") or {}),
            "vector_score": item.get("vector_score"),
            "keyword_score": item.get("keyword_score"),
            "final_score": item.get("final_score"),
            "parent_topic": item.get("parent_topic"),
            "images": item.get("images", []),
        }
        return RAGRetrieveItem(content=content, score=score, source=source, metadata=metadata, raw=item)
