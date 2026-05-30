"""配置数据模型"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


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
            "api_key": "***" if self.api_key else None,
            "api_url": self.api_url,
            "model_name": self.model_name,
            "parameters": self.parameters
        }


@dataclass
class RAGConfig:
    """MS-RAG服务配置"""
    enabled: bool = True
    base_url: str = "http://127.0.0.1:8001"
    retrieve_path: str = "/api/v1/retrieve"
    qa_path: str = "/api/v1/qa"
    timeout_seconds: int = 30
    top_k: int = 5


@dataclass
class MCPStdioConfig:
    """MCP stdio传输配置"""
    command: str = "python"
    args: List[str] = field(default_factory=lambda: ["main.py"])
    cwd: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)


@dataclass
class MCPEndpointConfig:
    """MCP远程传输配置"""
    url: str = ""
    api_key: Optional[str] = None


@dataclass
class MCPHarnessConfig:
    """MCP网关配置"""
    enabled: bool = True
    transport: str = "stdio"
    timeout_seconds: int = 60
    health_check_on_startup: bool = True
    health_check_mode: str = "background"
    required_meta_tools: List[str] = field(default_factory=lambda: ["search_profiler_tools", "execute_profiler_tool"])
    stdio: MCPStdioConfig = field(default_factory=MCPStdioConfig)
    sse: MCPEndpointConfig = field(default_factory=lambda: MCPEndpointConfig(url="http://127.0.0.1:8765/sse"))
    websocket: MCPEndpointConfig = field(default_factory=lambda: MCPEndpointConfig(url="ws://127.0.0.1:8765"))

    def to_mcp_client_config(self) -> Dict[str, Any]:
        if self.transport == "stdio":
            return {
                "transport": "stdio",
                "command": self.stdio.command,
                "args": self.stdio.args,
                "cwd": self.stdio.cwd,
                "env": self.stdio.env,
                "timeout": self.timeout_seconds,
            }
        if self.transport == "sse":
            return {
                "transport": "sse",
                "server_url": self.sse.url,
                "api_key": self.sse.api_key,
                "timeout": self.timeout_seconds,
            }
        if self.transport == "websocket":
            return {
                "transport": "websocket",
                "server_url": self.websocket.url,
                "api_key": self.websocket.api_key,
                "timeout": self.timeout_seconds,
            }
        return {"transport": self.transport, "timeout": self.timeout_seconds}


@dataclass
class LLMAssistanceConfig:
    """受控 LLM 辅助配置"""
    enabled: bool = False
    query_rewrite_enabled: bool = True
    candidate_recommendation_enabled: bool = True
    parameter_extraction_enabled: bool = True
    summary_enhancement_enabled: bool = False
    timeout_seconds: float = 3.0
    max_candidates: int = 5
    max_evidence_chars: int = 6000


@dataclass
class OrchestratorConfig:
    """Orchestrator执行策略配置"""
    chat_mode: str = "fixed_template"
    intent_strategy: str = "rule_first_llm_fallback"
    high_confidence_threshold: float = 0.85
    low_confidence_threshold: float = 0.60
    auto_execute: bool = True
    max_auto_steps: int = 5
    retry_count: int = 1
    require_confirmation_for_side_effects: bool = True
    validate_path_mode: str = "format_only"
    rag_after_mcp_policy: str = "conditional"
    mcp_unavailable_policy: str = "ask_before_rag_fallback"
    report_policy: str = "conditional"
    side_effect_tool_patterns: List[str] = field(default_factory=lambda: [
        "delete_*", "write_*", "export_*", "start_*", "stop_*",
        "restart_*", "submit_*", "rebuild_*"
    ])


@dataclass
class StorageConfig:
    """存储配置"""
    sqlite_path: str = "./sessions/sessions.db"


@dataclass
class ReportConfig:
    """报告配置"""
    format: str = "markdown"
    save_to_session_db: bool = True
    enable_pdf_export: bool = False


@dataclass
class AgentConfig:
    """Agent配置"""
    llm: LLMConfig
    mcp_server_url: str = "http://localhost:5000"
    knowledge_base_path: str = "./knowledge/docs"
    case_lib_path: str = "./cases"
    session_storage_path: str = "./sessions"
    rag: RAGConfig = field(default_factory=RAGConfig)
    mcp_harness: MCPHarnessConfig = field(default_factory=MCPHarnessConfig)
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    llm_assistance: LLMAssistanceConfig = field(default_factory=LLMAssistanceConfig)

    def to_dict(self) -> dict:
        return {
            "llm": self.llm.to_dict(),
            "mcp_server_url": self.mcp_server_url,
            "knowledge_base_path": self.knowledge_base_path,
            "case_lib_path": self.case_lib_path,
            "session_storage_path": self.session_storage_path,
            "rag": self.rag.__dict__,
            "mcp_harness": {
                "enabled": self.mcp_harness.enabled,
                "transport": self.mcp_harness.transport,
                "timeout_seconds": self.mcp_harness.timeout_seconds,
            },
            "orchestrator": self.orchestrator.__dict__,
            "storage": self.storage.__dict__,
            "report": self.report.__dict__,
        }
