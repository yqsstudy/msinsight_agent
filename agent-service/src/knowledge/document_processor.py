"""文档处理器 - 加载和处理知识文档"""

from typing import List, Dict, Any
import os
import re


class DocumentProcessor:
    """文档处理器"""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def load_documents(self, documents_path: str) -> List[Dict[str, Any]]:
        """
        加载文档

        Args:
            documents_path: 文档目录路径

        Returns:
            文档列表
        """
        documents = []

        if not os.path.exists(documents_path):
            return documents

        for filename in os.listdir(documents_path):
            if filename.endswith((".md", ".txt", ".rst")):
                filepath = os.path.join(documents_path, filename)
                doc = self._load_single_document(filepath)
                if doc:
                    documents.append(doc)

        return documents

    def _load_single_document(self, filepath: str) -> Dict[str, Any]:
        """加载单个文档"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            doc_id = os.path.basename(filepath).rsplit(".", 1)[0]

            return {
                "doc_id": doc_id,
                "filepath": filepath,
                "content": content,
                "metadata": {
                    "filename": os.path.basename(filepath),
                    "size": len(content)
                }
            }
        except Exception as e:
            print(f"Error loading document {filepath}: {e}")
            return None

    def chunk_documents(
        self,
        documents: List[Dict[str, Any]],
        chunk_size: int = None,
        chunk_overlap: int = None
    ) -> List[Dict[str, Any]]:
        """
        将文档分块

        Args:
            documents: 文档列表
            chunk_size: 块大小
            chunk_overlap: 块重叠

        Returns:
            分块后的文档列表
        """
        chunk_size = chunk_size or self.chunk_size
        chunk_overlap = chunk_overlap or self.chunk_overlap

        chunks = []

        for doc in documents:
            doc_chunks = self._chunk_text(
                doc.get("content", ""),
                chunk_size,
                chunk_overlap
            )

            for i, chunk_content in enumerate(doc_chunks):
                chunks.append({
                    "doc_id": doc.get("doc_id"),
                    "chunk_id": str(i),
                    "content": chunk_content,
                    "metadata": doc.get("metadata", {})
                })

        return chunks

    def _chunk_text(
        self,
        text: str,
        chunk_size: int,
        chunk_overlap: int
    ) -> List[str]:
        """文本分块"""
        # 按段落分割
        paragraphs = re.split(r'\n\s*\n', text)

        chunks = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) <= chunk_size:
                current_chunk += "\n\n" + para if current_chunk else para
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())

                # 处理超长段落
                if len(para) > chunk_size:
                    # 按句子分割
                    sentences = re.split(r'[。！？.!?]', para)
                    for sentence in sentences:
                        sentence = sentence.strip()
                        if len(sentence) > chunk_size:
                            # 强制分割
                            for j in range(0, len(sentence), chunk_size - chunk_overlap):
                                chunks.append(sentence[j:j + chunk_size])
                        elif sentence:
                            chunks.append(sentence)
                    current_chunk = ""
                else:
                    current_chunk = para

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks
