"""案例库管理器"""

import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
import os

from ..models import AnalysisCase, Diagnosis, Suggestion
from ..knowledge.vector_store import VectorStore


class CaseLibManager:
    """案例库管理"""

    def __init__(self, storage_path: str = "./cases", vector_store: VectorStore = None):
        self.storage_path = storage_path
        self.vector_store = vector_store
        self._ensure_storage_dir()

    def _ensure_storage_dir(self):
        """确保存储目录存在"""
        os.makedirs(self.storage_path, exist_ok=True)

    def save_case(self, case: AnalysisCase) -> str:
        """
        保存案例

        Args:
            case: 案例对象或字典

        Returns:
            案例ID
        """
        # 支持字典输入
        if isinstance(case, dict):
            case = self._dict_to_case(case)

        if not case.id:
            case.id = str(uuid.uuid4())

        case.created_at = case.created_at or datetime.now()

        # 保存到文件
        case_file = os.path.join(self.storage_path, f"{case.id}.json")
        with open(case_file, "w", encoding="utf-8") as f:
            json.dump(case.to_dict(), f, ensure_ascii=False, indent=2)

        # 添加到向量存储
        if self.vector_store:
            self.vector_store.add_documents([{
                "doc_id": case.id,
                "chunk_id": "case",
                "content": case.problem_description
            }])

        return case.id

    def load_case(self, case_id: str) -> Optional[AnalysisCase]:
        """加载案例"""
        case_file = os.path.join(self.storage_path, f"{case_id}.json")

        if not os.path.exists(case_file):
            return None

        with open(case_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        return self._dict_to_case(data)

    def _dict_to_case(self, data: dict) -> AnalysisCase:
        """字典转案例对象"""
        diagnosis = None
        if data.get("diagnosis"):
            diag_data = data["diagnosis"]
            if isinstance(diag_data, dict):
                diagnosis = Diagnosis(
                    root_cause=diag_data.get("root_cause", ""),
                    evidence=diag_data.get("evidence", []),
                )
            elif isinstance(diag_data, Diagnosis):
                diagnosis = diag_data

        suggestions = []
        for s in data.get("suggestions", []):
            if isinstance(s, dict):
                suggestions.append(Suggestion(
                    description=s.get("description", ""),
                    priority=s.get("priority", 0),
                    expected_improvement=s.get("expected_improvement", ""),
                    action_items=s.get("action_items", []),
                    knowledge_source=s.get("knowledge_source")
                ))
            elif isinstance(s, Suggestion):
                suggestions.append(s)

        return AnalysisCase(
            id=data.get("id"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            problem_description=data.get("problem_description", ""),
            problem_type=data.get("problem_type", ""),
            diagnosis=diagnosis,
            suggestions=suggestions,
            adopted=data.get("adopted", False),
            user_feedback=data.get("user_feedback")
        )

    def find_similar_cases(
        self,
        problem_description: str,
        top_k: int = 5
    ) -> List[AnalysisCase]:
        """
        查找相似案例

        Args:
            problem_description: 问题描述
            top_k: 返回数量

        Returns:
            相似案例列表
        """
        if not self.vector_store:
            return []

        results = self.vector_store.similarity_search(problem_description, top_k)
        cases = []

        for result in results:
            case = self.load_case(result.get("doc_id", ""))
            if case:
                cases.append(case)

        return cases

    def update_feedback(
        self,
        case_id: str,
        adopted: bool,
        user_comment: str = None
    ):
        """更新用户反馈"""
        case = self.load_case(case_id)
        if case:
            case.adopted = adopted
            case.user_feedback = user_comment
            self.save_case(case)

    def list_cases(self, limit: int = 50) -> List[AnalysisCase]:
        """列出所有案例"""
        cases = []

        for filename in os.listdir(self.storage_path):
            if filename.endswith(".json"):
                case_id = filename[:-5]
                case = self.load_case(case_id)
                if case:
                    cases.append(case)

        # 按创建时间排序
        cases.sort(key=lambda x: x.created_at or datetime.min, reverse=True)
        return cases[:limit]

    def delete_case(self, case_id: str) -> bool:
        """删除案例"""
        case_file = os.path.join(self.storage_path, f"{case_id}.json")

        if os.path.exists(case_file):
            os.remove(case_file)
            return True
        return False

    def create_case_from_report(
        self,
        problem_description: str,
        problem_type: str,
        diagnosis: Diagnosis,
        suggestions: List[Suggestion]
    ) -> AnalysisCase:
        """从报告创建案例"""
        case = AnalysisCase(
            id=str(uuid.uuid4()),
            created_at=datetime.now(),
            problem_description=problem_description,
            problem_type=problem_type,
            diagnosis=diagnosis,
            suggestions=suggestions,
            adopted=False
        )
        return case
