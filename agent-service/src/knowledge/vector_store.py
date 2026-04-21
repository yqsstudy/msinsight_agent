"""向量存储 - 基于ChromaDB的轻量级向量存储"""

from typing import List, Dict, Any, Optional
import os


class VectorStore:
    """向量存储"""

    def __init__(self, storage_path: str = "./knowledge/vectors"):
        self.storage_path = storage_path
        self._client = None
        self._collection = None

    def _get_client(self):
        """懒加载ChromaDB客户端"""
        if self._client is None:
            try:
                import chromadb
                self._client = chromadb.PersistentClient(path=self.storage_path)
                self._collection = self._client.get_or_create_collection(
                    name="knowledge_base",
                    metadata={"hnsw:space": "cosine"}
                )
            except ImportError:
                raise ImportError("请安装chromadb: pip install chromadb")
        return self._client

    def add_documents(self, documents: List[Dict[str, Any]]):
        """
        添加文档到向量存储

        Args:
            documents: 文档列表，每个文档包含:
                - doc_id: 文档ID
                - chunk_id: 块ID
                - content: 文本内容
                - embedding: 向量嵌入（可选，如果不提供则自动生成）
        """
        self._get_client()

        ids = []
        contents = []
        metadatas = []

        for doc in documents:
            chunk_id = f"{doc.get('doc_id')}_{doc.get('chunk_id', '0')}"
            ids.append(chunk_id)
            contents.append(doc.get("content", ""))
            metadatas.append({
                "doc_id": doc.get("doc_id", ""),
                "chunk_id": doc.get("chunk_id", "0")
            })

        if ids:
            self._collection.add(
                ids=ids,
                documents=contents,
                metadatas=metadatas
            )

    def similarity_search(
        self,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        相似度搜索

        Args:
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            相似文档列表
        """
        self._get_client()

        results = self._collection.query(
            query_texts=[query],
            n_results=top_k
        )

        documents = []
        if results and results.get("ids"):
            for i, doc_id in enumerate(results["ids"][0]):
                documents.append({
                    "doc_id": results["metadatas"][0][i].get("doc_id", ""),
                    "chunk_id": results["metadatas"][0][i].get("chunk_id", "0"),
                    "content": results["documents"][0][i] if results.get("documents") else "",
                    "score": 1 - results["distances"][0][i] if results.get("distances") else 0.0
                })

        return documents

    def delete_document(self, doc_id: str):
        """删除文档"""
        self._get_client()
        # ChromaDB需要通过ID删除，这里简化处理
        # 实际应用中需要维护doc_id到chunk_ids的映射

    def clear(self):
        """清空向量存储"""
        if self._client and self._collection:
            self._client.delete_collection("knowledge_base")
            self._collection = self._client.get_or_create_collection(
                name="knowledge_base",
                metadata={"hnsw:space": "cosine"}
            )

    def count(self) -> int:
        """获取文档数量"""
        self._get_client()
        return self._collection.count()
