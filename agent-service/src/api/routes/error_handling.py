"""错误处理状态API"""

from fastapi import APIRouter

from ...error_handling import circuit_registry, fallback_manager, error_handler

router = APIRouter(prefix="/error-handling", tags=["Error Handling"])


@router.get("/circuit-breakers")
async def get_circuit_breakers():
    """获取所有熔断器状态"""
    return circuit_registry.get_all_states()


@router.get("/circuit-breakers/{name}")
async def get_circuit_breaker(name: str):
    """获取指定熔断器状态"""
    cb = circuit_registry.get_or_create(name)
    return cb.get_state()


@router.post("/circuit-breakers/{name}/reset")
async def reset_circuit_breaker(name: str):
    """重置熔断器"""
    cb = circuit_registry.get_or_create(name)
    cb.reset()
    return {"status": "ok", "message": f"Circuit breaker '{name}' reset"}


@router.get("/fallbacks")
async def get_fallbacks():
    """获取降级策略状态"""
    return fallback_manager.get_stats()


@router.get("/errors/stats")
async def get_error_stats():
    """获取错误统计"""
    return error_handler.get_error_stats()
