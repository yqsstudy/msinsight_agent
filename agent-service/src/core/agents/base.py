from pydantic import BaseModel
from typing import Literal, Any, List, Optional
from abc import ABC, abstractmethod

class AgentRequirement(BaseModel):
    """Signal raised when a sub-agent is blocked and needs user input."""
    input_type: Literal["choice", "text", "params", "path", "confirm"]
    question: str
    options: List[dict] = []
    metadata: dict  # Snapshot required to resume execution

class AgentResult(BaseModel):
    """The outcome of a sub-agent's execution."""
    status: Literal["completed", "failed", "suspended"]
    evidence_ids: List[str] = []
    requirement: Optional[AgentRequirement] = None
    error_msg: Optional[str] = None

class BaseWorkerAgent(ABC):
    @abstractmethod
    async def run(self, session_id: str, plan_step_id: str, goal: str, blackboard: dict) -> AgentResult:
        """Initial execution entry point."""
        pass
        
    @abstractmethod
    async def resume(self, session_id: str, plan_step_id: str, user_input: Any, suspended_metadata: dict) -> AgentResult:
        """Resume execution from a suspended state."""
        pass
