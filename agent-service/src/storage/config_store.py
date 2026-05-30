"""配置存储"""

import json
import os
from typing import Dict, Any, Optional

from ..models import (
    LLMConfig, AgentConfig, RAGConfig, MCPHarnessConfig, MCPStdioConfig,
    MCPEndpointConfig, OrchestratorConfig, StorageConfig, ReportConfig,
    LLMAssistanceConfig
)


class ConfigStore:
    """配置存储"""

    DEFAULT_CONFIG = {
        "llm": {
            "default_provider": "claude",
            "providers": {
                "claude": {
                    "api_key": "",
                    "api_url": "https://api.anthropic.com",
                    "model": "claude-sonnet-4-6",
                    "parameters": {
                        "temperature": 0.7,
                        "max_tokens": 4096
                    }
                },
                "openai": {
                    "api_key": "",
                    "api_url": "https://api.openai.com/v1",
                    "model": "gpt-4",
                    "parameters": {
                        "temperature": 0.7,
                        "max_tokens": 4096
                    }
                },
                "local": {
                    "api_key": "",
                    "api_url": "http://localhost:8000/v1",
                    "model": "local-model",
                    "parameters": {
                        "temperature": 0.7,
                        "max_tokens": 4096
                    }
                }
            }
        },
        "mcp": {
            "transport": "http",
            "server_url": "http://localhost:5000",
            "timeout": 30,
            "reconnect": True,
            "reconnect_interval": 5
        },
        "knowledge": {
            "documents_path": "./knowledge/docs",
            "vector_store_path": "./knowledge/vectors"
        },
        "case_lib": {
            "storage_path": "./cases"
        },
        "session": {
            "storage_path": "./sessions"
        }
    }

    def __init__(self, config_path: str = "./config/config.yaml"):
        if not os.path.exists(config_path):
            package_config = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.yaml"))
            if os.path.exists(package_config):
                config_path = package_config
        self.config_path = config_path
        self._config: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self):
        """加载配置"""
        if os.path.exists(self.config_path):
            try:
                import yaml
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self._config = yaml.safe_load(f) or {}
            except ImportError:
                # 如果没有yaml库，尝试json
                json_path = self.config_path.replace(".yaml", ".json")
                if os.path.exists(json_path):
                    with open(json_path, "r", encoding="utf-8") as f:
                        self._config = json.load(f)
                else:
                    self._config = self.DEFAULT_CONFIG.copy()
            except Exception:
                self._config = self.DEFAULT_CONFIG.copy()
        else:
            self._config = self.DEFAULT_CONFIG.copy()

    def get(self, key: str = None, default: Any = None) -> Any:
        """获取配置"""
        if key is None:
            return self._config

        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value: Any):
        """设置配置"""
        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value

    def get_llm_config(self, provider: str = None) -> LLMConfig:
        """获取LLM配置"""
        provider = provider or self.get("llm.default_provider", "claude")
        provider_config = self.get(f"llm.providers.{provider}", {})

        return LLMConfig(
            provider=provider,
            api_key=provider_config.get("api_key"),
            api_url=provider_config.get("api_url", ""),
            model_name=provider_config.get("model", ""),
            parameters=provider_config.get("parameters", {})
        )

    def set_llm_config(self, provider: str, config: Dict[str, Any]):
        """设置LLM配置"""
        self.set(f"llm.providers.{provider}", config)
        self.save()

    def get_agent_config(self) -> AgentConfig:
        """获取Agent配置"""
        llm_config = self.get_llm_config()

        return AgentConfig(
            llm=llm_config,
            mcp_server_url=self.get("mcp.server_url", "http://localhost:5000"),
            knowledge_base_path=self.get("knowledge.documents_path", "./knowledge/docs"),
            case_lib_path=self.get("case_lib.storage_path", "./cases"),
            session_storage_path=self.get("session.storage_path", "./sessions"),
            rag=self.get_rag_config(),
            mcp_harness=self.get_mcp_harness_config(),
            orchestrator=self.get_orchestrator_config(),
            storage=self.get_storage_config(),
            report=self.get_report_config(),
            llm_assistance=self.get_llm_assistance_config(),
        )

    def get_rag_config(self) -> RAGConfig:
        """获取RAG配置"""
        return RAGConfig(
            enabled=self.get("rag.enabled", True),
            base_url=self.get("rag.base_url", "http://127.0.0.1:8001"),
            retrieve_path=self.get("rag.retrieve_path", "/api/v1/retrieve"),
            qa_path=self.get("rag.qa_path", "/api/v1/qa"),
            timeout_seconds=self.get("rag.timeout_seconds", 30),
            top_k=self.get("rag.top_k", 5),
        )

    def get_mcp_harness_config(self) -> MCPHarnessConfig:
        """获取MCP Harness配置"""
        return MCPHarnessConfig(
            enabled=self.get("mcp.enabled", True),
            transport=self.get("mcp.transport", "stdio"),
            timeout_seconds=self.get("mcp.timeout", self.get("mcp.timeout_seconds", 60)),
            stdio=MCPStdioConfig(
                command=self.get("mcp.command", "python"),
                args=self.get("mcp.args", ["main.py", "--transport", "stdio"]),
                cwd=self.get("mcp.cwd"),
                env=self.get("mcp.env", {}),
            ),
            sse=MCPEndpointConfig(
                url=self.get("mcp.sse_url", "http://127.0.0.1:8765/sse"),
                api_key=self.get("mcp.api_key"),
            ),
            websocket=MCPEndpointConfig(
                url=self.get("mcp.websocket_url", "ws://127.0.0.1:8765"),
                api_key=self.get("mcp.api_key"),
            ),
        )

    def get_orchestrator_config(self) -> OrchestratorConfig:
        """获取Orchestrator配置"""
        return OrchestratorConfig(
            auto_execute=self.get("orchestrator.auto_execute", True),
            max_auto_steps=self.get("orchestrator.max_auto_steps", 5),
            retry_count=self.get("orchestrator.retry_count", 1),
            require_confirmation_for_side_effects=self.get("orchestrator.require_confirmation_for_side_effects", True),
            side_effect_tool_patterns=self.get("orchestrator.side_effect_tool_patterns", [
                "delete_*", "write_*", "export_*", "start_*", "stop_*",
                "restart_*", "submit_*", "rebuild_*"
            ]),
        )

    def get_storage_config(self) -> StorageConfig:
        """获取存储配置"""
        sqlite_path = self.get("storage.sqlite_path", "./sessions/sessions.db")
        if sqlite_path != ":memory:" and not os.path.isabs(sqlite_path):
            sqlite_path = os.path.abspath(os.path.join(os.path.dirname(self.config_path), "..", sqlite_path))
        return StorageConfig(sqlite_path=sqlite_path)

    def get_report_config(self) -> ReportConfig:
        """获取报告配置"""
        return ReportConfig(
            format=self.get("report.format", "markdown"),
            save_to_session_db=self.get("report.save_to_session_db", True),
            enable_pdf_export=self.get("report.enable_pdf_export", False),
        )

    def get_llm_router_config(self) -> Dict[str, Any]:
        """获取 LLMRouter 需要的完整配置结构。"""
        return self.get("llm", {})

    def get_llm_assistance_config(self) -> LLMAssistanceConfig:
        """获取受控 LLM 辅助配置。"""
        return LLMAssistanceConfig(
            enabled=self.get("llm_assistance.enabled", False),
            query_rewrite_enabled=self.get("llm_assistance.query_rewrite_enabled", True),
            candidate_recommendation_enabled=self.get("llm_assistance.candidate_recommendation_enabled", True),
            parameter_extraction_enabled=self.get("llm_assistance.parameter_extraction_enabled", True),
            summary_enhancement_enabled=self.get("llm_assistance.summary_enhancement_enabled", False),
            timeout_seconds=float(self.get("llm_assistance.timeout_seconds", 3.0)),
            max_candidates=int(self.get("llm_assistance.max_candidates", 5)),
            max_evidence_chars=int(self.get("llm_assistance.max_evidence_chars", 6000)),
        )

    def get_mcp_config(self) -> Dict[str, Any]:
        """获取MCP配置"""
        return {
            "transport": self.get("mcp.transport", "http"),
            "server_url": self.get("mcp.server_url", "http://localhost:5000"),
            "command": self.get("mcp.command"),
            "args": self.get("mcp.args"),
            "env": self.get("mcp.env"),
            "cwd": self.get("mcp.cwd"),
            "api_key": self.get("mcp.api_key"),
            "timeout": self.get("mcp.timeout", 30),
            "reconnect": self.get("mcp.reconnect", True),
            "reconnect_interval": self.get("mcp.reconnect_interval", 5)
        }

    def save(self):
        """保存配置"""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

        try:
            import yaml
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(self._config, f, default_flow_style=False, allow_unicode=True)
        except ImportError:
            # 使用JSON保存
            json_path = self.config_path.replace(".yaml", ".json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)

    def reload(self):
        """重新加载配置"""
        self._load_config()
