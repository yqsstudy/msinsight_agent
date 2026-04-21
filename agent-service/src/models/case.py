"""案例库数据模型"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List

from .report import Diagnosis, Suggestion


@dataclass
class AnalysisCase:
    """分析案例"""
    id: str
    created_at: datetime
    problem_description: str
    problem_type: str
    diagnosis: Optional[Diagnosis] = None
    suggestions: List[Suggestion] = field(default_factory=list)
    adopted: bool = False
    user_feedback: Optional[str] = None
    embedding: Optional[List[float]] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "problem_description": self.problem_description,
            "problem_type": self.problem_type,
            "diagnosis": self.diagnosis.to_dict() if self.diagnosis else None,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "adopted": self.adopted,
            "user_feedback": self.user_feedback
        }
