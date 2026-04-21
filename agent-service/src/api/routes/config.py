"""配置管理API"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...storage import ConfigStore

router = APIRouter(prefix="/api/config", tags=["config"])

# 全局配置存储实例
_config_store: Optional[ConfigStore] = None


def get_config_store() -> ConfigStore:
    global _config_store
    if _config_store is None:
        _config_store = ConfigStore()
    return _config_store


class LLMConfigRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    api_url: Optional[str] = None
    model_name: Optional[str] = None
    parameters: Optional[dict] = None


@router.get("")
async def get_config():
    """获取完整配置"""
    store = get_config_store()
    config = store.get()
    return {"config": config}


@router.get("/llm")
async def get_llm_config(provider: Optional[str] = None):
    """获取LLM配置"""
    store = get_config_store()
    llm_config = store.get_llm_config(provider)
    return {"llm_config": llm_config.to_dict()}


@router.put("/llm")
async def update_llm_config(request: LLMConfigRequest):
    """更新LLM配置"""
    store = get_config_store()

    config = {}
    if request.api_key is not None:
        config["api_key"] = request.api_key
    if request.api_url is not None:
        config["api_url"] = request.api_url
    if request.model_name is not None:
        config["model"] = request.model_name
    if request.parameters is not None:
        config["parameters"] = request.parameters

    store.set_llm_config(request.provider, config)

    return {"success": True}


@router.put("/llm/default-provider")
async def set_default_provider(provider: str):
    """设置默认LLM提供商"""
    store = get_config_store()
    store.set("llm.default_provider", provider)
    store.save()
    return {"success": True}


@router.get("/mcp")
async def get_mcp_config():
    """获取MCP配置"""
    store = get_config_store()
    return {
        "mcp_config": {
            "server_url": store.get("mcp.server_url"),
            "timeout": store.get("mcp.timeout")
        }
    }


@router.put("/mcp")
async def update_mcp_config(server_url: str, timeout: int = 30):
    """更新MCP配置"""
    store = get_config_store()
    store.set("mcp.server_url", server_url)
    store.set("mcp.timeout", timeout)
    store.save()
    return {"success": True}
