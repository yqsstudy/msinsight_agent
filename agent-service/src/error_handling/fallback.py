"""降级策略 - Fallback机制"""

import asyncio
from typing import Callable, Any, Dict, Optional, List, Type
from dataclasses import dataclass, field
from enum import Enum

from ..observability import get_logger

logger = get_logger(__name__)


class FallbackType(Enum):
    """降级类型"""
    DEFAULT_VALUE = "default_value"       # 返回默认值
    CACHED_VALUE = "cached_value"         # 返回缓存值
    ALTERNATIVE_METHOD = "alternative"     # 使用替代方法
    SIMPLIFIED_METHOD = "simplified"       # 使用简化方法
    GRACEFUL_DEGRADATION = "graceful"      # 优雅降级


@dataclass
class FallbackConfig:
    """降级配置"""
    fallback_type: FallbackType
    default_value: Any = None
    alternative_func: Optional[Callable] = None
    cache_key: Optional[str] = None
    message: str = "服务降级中"


class FallbackStrategy:
    """降级策略基类"""

    def __init__(self, name: str, config: FallbackConfig = None):
        self.name = name
        self.config = config or FallbackConfig(FallbackType.DEFAULT_VALUE)
        self._cache: Dict[str, Any] = {}

    async def execute(self, *args, **kwargs) -> Any:
        """执行降级策略"""
        if self.config.fallback_type == FallbackType.DEFAULT_VALUE:
            return self._default_value_fallback()

        elif self.config.fallback_type == FallbackType.CACHED_VALUE:
            return self._cached_value_fallback()

        elif self.config.fallback_type == FallbackType.ALTERNATIVE_METHOD:
            return await self._alternative_fallback(*args, **kwargs)

        elif self.config.fallback_type == FallbackType.SIMPLIFIED_METHOD:
            return await self._simplified_fallback(*args, **kwargs)

        elif self.config.fallback_type == FallbackType.GRACEFUL_DEGRADATION:
            return self._graceful_fallback()

        return None

    def _default_value_fallback(self) -> Any:
        """默认值降级"""
        logger.info(f"Using default value fallback: strategy=self.name")
        return self.config.default_value

    def _cached_value_fallback(self) -> Any:
        """缓存值降级"""
        cache_key = self.config.cache_key or self.name
        if cache_key in self._cache:
            logger.info(f"Using cached value fallback: strategy=self.name")
            return self._cache[cache_key]
        logger.warning(f"No cached value available: strategy=self.name")
        return self.config.default_value

    async def _alternative_fallback(self, *args, **kwargs) -> Any:
        """替代方法降级"""
        if self.config.alternative_func:
            logger.info(f"Using alternative method fallback: strategy=self.name")
            if asyncio.iscoroutinefunction(self.config.alternative_func):
                return await self.config.alternative_func(*args, **kwargs)
            return self.config.alternative_func(*args, **kwargs)
        return self.config.default_value

    async def _simplified_fallback(self, *args, **kwargs) -> Any:
        """简化方法降级"""
        logger.info(f"Using simplified method fallback: strategy=self.name")
        # 子类实现
        return self.config.default_value

    def _graceful_fallback(self) -> Any:
        """优雅降级"""
        logger.info(f"Graceful degradation: strategy=self.name")
        return {
            "degraded": True,
            "message": self.config.message,
            "data": self.config.default_value,
        }

    def update_cache(self, key: str, value: Any):
        """更新缓存"""
        self._cache[key] = value


class MCPToolFallback(FallbackStrategy):
    """MCP工具降级策略"""

    # 工具默认返回值
    DEFAULT_RESULTS = {
        "parse_data": {"data_id": "fallback", "data_type": "unknown"},
        "get_overview": {"problem_types": [], "metrics": {}},
        "get_comm_domains": {"domains": []},
        "analyze_slow_cards": {"slow_cards": [], "analysis": {}},
        "analyze_memory": {"issues": [], "metrics": {}},
    }

    def __init__(self, tool_name: str):
        default_value = self.DEFAULT_RESULTS.get(tool_name, {})
        config = FallbackConfig(
            fallback_type=FallbackType.DEFAULT_VALUE,
            default_value=default_value,
            message=f"工具 {tool_name} 降级，返回默认结果"
        )
        super().__init__(f"mcp_tool_{tool_name}", config)
        self.tool_name = tool_name

    async def _simplified_fallback(self, *args, **kwargs) -> Any:
        """简化分析 - 返回空结果而非错误"""
        return {
            **self.config.default_value,
            "fallback": True,
            "message": f"{self.tool_name} 降级执行"
        }


class LLMFallback(FallbackStrategy):
    """LLM降级策略"""

    def __init__(self, alternative_llm: Callable = None):
        config = FallbackConfig(
            fallback_type=FallbackType.ALTERNATIVE_METHOD if alternative_llm else FallbackType.DEFAULT_VALUE,
            alternative_func=alternative_llm,
            default_value={"content": "AI服务暂时不可用，请稍后重试"},
            message="LLM服务降级"
        )
        super().__init__("llm_fallback", config)


class AnalysisFallback(FallbackStrategy):
    """分析流程降级策略"""

    def __init__(self):
        config = FallbackConfig(
            fallback_type=FallbackType.GRACEFUL_DEGRADATION,
            default_value={
                "problems": [],
                "suggestions": ["分析服务暂时不可用，请稍后重试"],
            },
            message="分析服务降级，返回基础结果"
        )
        super().__init__("analysis_fallback", config)


class FallbackManager:
    """降级管理器"""

    def __init__(self):
        self._strategies: Dict[str, FallbackStrategy] = {}
        self._fallback_counts: Dict[str, int] = {}

    def register(self, name: str, strategy: FallbackStrategy):
        """注册降级策略"""
        self._strategies[name] = strategy
        logger.info(f"Registered fallback strategy: name=name")

    def get(self, name: str) -> Optional[FallbackStrategy]:
        """获取降级策略"""
        return self._strategies.get(name)

    async def execute_fallback(
        self,
        name: str,
        error: Exception = None,
        *args,
        **kwargs
    ) -> Any:
        """执行降级"""
        strategy = self._strategies.get(name)
        if not strategy:
            logger.warning(f"No fallback strategy found: name=name")
            return None

        self._fallback_counts[name] = self._fallback_counts.get(name, 0) + 1

        logger.warning(
            f"Executing fallback strategy",
            strategy=name,
            error=str(error) if error else None
        )

        return await strategy.execute(*args, **kwargs)

    def get_stats(self) -> Dict[str, Any]:
        """获取降级统计"""
        return {
            "registered_strategies": list(self._strategies.keys()),
            "fallback_counts": dict(self._fallback_counts),
        }


# 全局降级管理器
fallback_manager = FallbackManager()

# 注册默认降级策略
for tool_name in MCPToolFallback.DEFAULT_RESULTS.keys():
    fallback_manager.register(f"mcp_tool_{tool_name}", MCPToolFallback(tool_name))

fallback_manager.register("llm", LLMFallback())
fallback_manager.register("analysis", AnalysisFallback())


def with_fallback(
    fallback_name: str,
    fallback_value: Any = None
):
    """
    降级装饰器

    Usage:
        @with_fallback("mcp_tool_parse_data")
        async def parse_data(path):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.warning(
                    f"Function failed, executing fallback",
                    function=func.__name__,
                    fallback=fallback_name,
                    error=str(e)
                )

                strategy = fallback_manager.get(fallback_name)
                if strategy:
                    return await strategy.execute(*args, **kwargs)

                if fallback_value is not None:
                    return fallback_value

                raise

        return wrapper

    import functools
    return decorator
