"""配置数据模型"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMConfig:
    """LLM配置"""
    provider: str  # "claude" | "openai" | "local"
    api_key: Optional[str] = None
    api_url: str = ""
    model_name: str = ""
    parameters: dict = field(default_factory=lambda: {
        "temperature": 0.7,
        "max_tokens": 4096
    })

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "api_key": "***" if self.api_key else None,  # 隐藏敏感信息
            "api_url": self.api_url,
            "model_name": self.model_name,
            "parameters": self.parameters
        }


@dataclass
class AgentConfig:
    """Agent配置"""
    llm: LLMConfig
    mcp_server_url: str = "http://localhost:5000"
    knowledge_base_path: str = "./knowledge/docs"
    case_lib_path: str = "./cases"
    session_storage_path: str = "./sessions"

    def to_dict(self) -> dict:
        return {
            "llm": self.llm.to_dict(),
            "mcp_server_url": self.mcp_server_url,
            "knowledge_base_path": self.knowledge_base_path,
            "case_lib_path": self.case_lib_path,
            "session_storage_path": self.session_storage_path
        }
