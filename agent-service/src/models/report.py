"""分析报告相关数据模型"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


@dataclass
class ToolCallRecord:
    """工具调用记录"""
    tool_name: str
    input_params: dict
    output: dict
    timestamp: datetime
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class Problem:
    """检测到的问题"""
    type: str  # "communication" | "memory" | "compute" | ...
    severity: str  # "high" | "medium" | "low"
    description: str
    location: str  # 问题位置（如：哪个卡、哪个迭代）

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "severity": self.severity,
            "description": self.description,
            "location": self.location
        }


@dataclass
class Diagnosis:
    """诊断结果"""
    root_cause: str
    evidence: List[str] = field(default_factory=list)
    analysis_process: List[ToolCallRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "root_cause": self.root_cause,
            "evidence": self.evidence,
            "analysis_process": [
                {
                    "tool_name": r.tool_name,
                    "timestamp": r.timestamp.isoformat(),
                    "success": r.success
                }
                for r in self.analysis_process
            ]
        }


@dataclass
class Suggestion:
    """优化建议"""
    description: str
    priority: int
    expected_improvement: str
    action_items: List[str] = field(default_factory=list)
    knowledge_source: Optional[str] = None  # 建议来源

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "priority": self.priority,
            "expected_improvement": self.expected_improvement,
            "action_items": self.action_items,
            "knowledge_source": self.knowledge_source
        }


@dataclass
class KnowledgeRef:
    """知识库引用"""
    doc_id: str
    chunk_id: str
    content: str
    relevance_score: float


@dataclass
class CaseRef:
    """案例引用"""
    case_id: str
    problem_description: str
    similarity_score: float


@dataclass
class DataInfo:
    """数据信息"""
    data_id: str
    data_type: str
    file_path: str
    summary: dict = field(default_factory=dict)


@dataclass
class AnalysisReport:
    """分析报告"""
    id: str = ""
    session_id: str = ""
    data_info: Optional[DataInfo] = None
    problems: List[Problem] = field(default_factory=list)
    diagnosis: Optional[Diagnosis] = None
    suggestions: List[Suggestion] = field(default_factory=list)
    knowledge_refs: List[KnowledgeRef] = field(default_factory=list)
    similar_cases: List[CaseRef] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "data_info": {
                "data_id": self.data_info.data_id,
                "data_type": self.data_info.data_type,
                "file_path": self.data_info.file_path,
                "summary": self.data_info.summary
            } if self.data_info else None,
            "problems": [p.to_dict() for p in self.problems],
            "diagnosis": self.diagnosis.to_dict() if self.diagnosis else None,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "knowledge_refs": [
                {
                    "doc_id": r.doc_id,
                    "content": r.content[:200] + "..." if len(r.content) > 200 else r.content,
                    "relevance_score": r.relevance_score
                }
                for r in self.knowledge_refs
            ],
            "similar_cases": [
                {
                    "case_id": c.case_id,
                    "problem_description": c.problem_description,
                    "similarity_score": c.similarity_score
                }
                for c in self.similar_cases
            ]
        }
