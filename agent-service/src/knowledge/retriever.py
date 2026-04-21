"""知识库检索器 - 混合检索：关键词 + 向量相似"""

from typing import List, Dict, Any, Optional
import os
import re

from .vector_store import VectorStore
from .document_processor import DocumentProcessor


class KnowledgeRetriever:
    """混合检索：关键词 + 向量相似"""

    def __init__(
        self,
        vector_store: VectorStore,
        documents_path: str = "./knowledge/docs",
        keyword_weight: float = 0.4,
        vector_weight: float = 0.6,
        top_k: int = 3
    ):
        self.vector_store = vector_store
        self.documents_path = documents_path
        self.keyword_weight = keyword_weight
        self.vector_weight = vector_weight
        self.top_k = top_k
        self.keyword_index: Dict[str, List[Dict]] = {}
        self._initialized = False

    def initialize(self):
        """初始化知识库"""
        if self._initialized:
            return

        # 加载文档并构建索引
        processor = DocumentProcessor()
        documents = processor.load_documents(self.documents_path)

        # 构建关键词索引
        self._build_keyword_index(documents)

        # 构建向量索引
        chunks = processor.chunk_documents(documents)
        self.vector_store.add_documents(chunks)

        self._initialized = True

    def retrieve(
        self,
        query: str,
        problem_type: str = None,
        top_k: int = None
    ) -> List[Dict[str, Any]]:
        """
        检索相关知识

        Args:
            query: 查询文本
            problem_type: 问题类型（用于关键词过滤）
            top_k: 返回结果数量

        Returns:
            检索结果列表
        """
        if not self._initialized:
            self.initialize()

        top_k = top_k or self.top_k

        # 1. 关键词检索
        keyword_results = self._keyword_search(query, problem_type)

        # 2. 向量相似检索
        vector_results = self.vector_store.similarity_search(query, top_k * 2)

        # 3. 混合排序
        merged = self._merge_results(keyword_results, vector_results)

        return merged[:top_k]

    def _build_keyword_index(self, documents: List[Dict[str, Any]]):
        """构建关键词索引"""
        for doc in documents:
            content = doc.get("content", "")
            doc_id = doc.get("doc_id", "")

            # 提取关键词
            keywords = self._extract_keywords(content)

            for keyword in keywords:
                if keyword not in self.keyword_index:
                    self.keyword_index[keyword] = []
                self.keyword_index[keyword].append({
                    "doc_id": doc_id,
                    "content": content[:500],  # 截断
                    "relevance": 1.0
                })

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        # 简单的关键词提取（可后续优化）
        keywords = set()

        # 中文分词（简单实现）
        chinese_words = re.findall(r'[\u4e00-\u9fa5]{2,}', text)
        keywords.update(chinese_words)

        # 英文单词
        english_words = re.findall(r'[A-Za-z]{3,}', text.lower())
        keywords.update(english_words)

        # 过滤停用词
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "be", "been"}
        keywords = keywords - stop_words

        return list(keywords)

    def _keyword_search(
        self,
        query: str,
        problem_type: str = None
    ) -> List[Dict[str, Any]]:
        """关键词检索"""
        results = []
        query_keywords = set(self._extract_keywords(query))

        if problem_type:
            query_keywords.add(problem_type)

        for keyword in query_keywords:
            if keyword in self.keyword_index:
                for item in self.keyword_index[keyword]:
                    results.append({
                        "doc_id": item["doc_id"],
                        "chunk_id": f"kw_{keyword}",
                        "content": item["content"],
                        "score": item["relevance"] * self.keyword_weight
                    })

        return results

    def _merge_results(
        self,
        keyword_results: List[Dict],
        vector_results: List[Dict]
    ) -> List[Dict]:
        """合并检索结果"""
        # 使用字典合并相同doc的结果
        merged = {}

        for item in keyword_results:
            key = item.get("doc_id", "")
            if key not in merged:
                merged[key] = item.copy()
            else:
                merged[key]["score"] += item["score"]

        for item in vector_results:
            key = item.get("doc_id", "")
            item["score"] = item.get("score", 0) * self.vector_weight
            if key not in merged:
                merged[key] = item.copy()
            else:
                merged[key]["score"] += item["score"]
                merged[key]["content"] = item.get("content", merged[key].get("content", ""))

        # 按分数排序
        results = sorted(merged.values(), key=lambda x: x.get("score", 0), reverse=True)
        return results
