"""错误处理模块"""

from .retry import RetryPolicy, RetryConfig, retry
from .circuit_breaker import CircuitBreaker, CircuitConfig, CircuitState, circuit_registry
from .handler import ErrorHandler, ErrorType, ErrorContext, error_handler
from .fallback import FallbackStrategy, FallbackConfig, FallbackManager, FallbackType, fallback_manager

__all__ = [
    # 重试
    "RetryPolicy",
    "RetryConfig",
    "retry",
    # 熔断器
    "CircuitBreaker",
    "CircuitConfig",
    "CircuitState",
    "circuit_registry",
    # 错误处理
    "ErrorHandler",
    "ErrorType",
    "ErrorContext",
    "error_handler",
    # 降级
    "FallbackStrategy",
    "FallbackConfig",
    "FallbackManager",
    "FallbackType",
    "fallback_manager",
]
