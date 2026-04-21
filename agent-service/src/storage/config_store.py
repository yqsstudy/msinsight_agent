"""配置存储"""

import json
import os
from typing import Dict, Any, Optional

from ..models import LLMConfig, AgentConfig


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
            session_storage_path=self.get("session.storage_path", "./sessions")
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
