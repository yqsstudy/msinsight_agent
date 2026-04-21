"""会话相关数据模型"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Any
from enum import Enum


class Option:
    """用户选择选项"""
    def __init__(self, value: str, label: str, description: str = ""):
        self.value = value
        self.label = label
        self.description = description

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "label": self.label,
            "description": self.description
        }


@dataclass
class AnalysisContext:
    """分析上下文"""
    data_path: Optional[str] = None
    data_id: Optional[str] = None
    data_type: Optional[str] = None
    problem_type: Optional[str] = None
    analysis_results: dict = field(default_factory=dict)
    pending_choices: Optional[List[Option]] = None


@dataclass
class Message:
    """对话消息"""
    id: str
    role: str  # "user" | "agent"
    content: str
    timestamp: datetime
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }


@dataclass
class Session:
    """分析会话"""
    id: str
    created_at: datetime
    updated_at: datetime
    messages: List[Message] = field(default_factory=list)
    state: str = "IDLE"
    context: AnalysisContext = field(default_factory=AnalysisContext)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "messages": [m.to_dict() for m in self.messages],
            "state": self.state,
            "context": {
                "data_path": self.context.data_path,
                "data_id": self.context.data_id,
                "data_type": self.context.data_type,
                "problem_type": self.context.problem_type,
                "analysis_results": self.context.analysis_results,
            }
        }
