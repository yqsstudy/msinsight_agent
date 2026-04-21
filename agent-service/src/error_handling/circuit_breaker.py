"""熔断器 - 防止级联故障"""

import asyncio
from datetime import datetime, timedelta
from typing import Callable, Any, Optional, Dict
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
import threading

from ..observability import get_logger

logger = get_logger(__name__)


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"          # 正常状态，允许请求
    OPEN = "open"              # 熔断状态，拒绝请求
    HALF_OPEN = "half_open"    # 半开状态，允许探测请求


@dataclass
class CircuitStats:
    """熔断器统计"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    consecutive_failures: int = 0
    last_failure_time: Optional[datetime] = None
    last_failure_error: Optional[str] = None


@dataclass
class CircuitConfig:
    """熔断器配置"""
    failure_threshold: int = 5          # 连续失败次数阈值
    success_threshold: int = 3          # 半开状态成功次数阈值
    timeout: float = 30.0               # 熔断超时时间（秒）
    half_open_max_calls: int = 3        # 半开状态最大探测请求数


class CircuitBreaker:
    """熔断器"""

    def __init__(
        self,
        name: str = "default",
        config: CircuitConfig = None,
        on_open: Callable = None,
        on_close: Callable = None
    ):
        self.name = name
        self.config = config or CircuitConfig()
        self.state = CircuitState.CLOSED
        self.stats = CircuitStats()
        self._lock = threading.RLock()
        self._half_open_calls = 0
        self._opened_at: Optional[datetime] = None

        # 回调
        self._on_open = on_open
        self._on_close = on_close

    def is_call_allowed(self) -> bool:
        """检查是否允许调用"""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True

            elif self.state == CircuitState.OPEN:
                # 检查是否超过超时时间
                if self._should_attempt_reset():
                    self._transition_to_half_open()
                    return True
                return False

            elif self.state == CircuitState.HALF_OPEN:
                # 半开状态限制请求数
                if self._half_open_calls < self.config.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False

        return False

    def _should_attempt_reset(self) -> bool:
        """检查是否应该尝试重置"""
        if not self._opened_at:
            return True

        elapsed = (datetime.utcnow() - self._opened_at).total_seconds()
        return elapsed >= self.config.timeout

    def _transition_to_open(self, error: Exception = None):
        """转换到熔断状态"""
        with self._lock:
            if self.state == CircuitState.OPEN:
                return

            old_state = self.state
            self.state = CircuitState.OPEN
            self._opened_at = datetime.utcnow()
            self._half_open_calls = 0

            logger.warning(
                f"Circuit breaker opened",
                circuit=self.name,
                consecutive_failures=self.stats.consecutive_failures,
                error=str(error) if error else None
            )

            if self._on_open:
                try:
                    self._on_open(self.name, error)
                except Exception as e:
                    logger.error(f"Circuit breaker on_open callback failed: {e}")

    def _transition_to_half_open(self):
        """转换到半开状态"""
        with self._lock:
            self.state = CircuitState.HALF_OPEN
            self._half_open_calls = 0

            logger.info(
                f"Circuit breaker entering half-open state",
                circuit=self.name
            )

    def _transition_to_closed(self):
        """转换到关闭状态"""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return

            old_state = self.state
            self.state = CircuitState.CLOSED
            self.stats.consecutive_failures = 0
            self._opened_at = None
            self._half_open_calls = 0

            logger.info(
                f"Circuit breaker closed",
                circuit=self.name
            )

            if self._on_close:
                try:
                    self._on_close(self.name)
                except Exception as e:
                    logger.error(f"Circuit breaker on_close callback failed: {e}")

    def record_success(self):
        """记录成功"""
        with self._lock:
            self.stats.total_calls += 1
            self.stats.successful_calls += 1
            self.stats.consecutive_failures = 0

            if self.state == CircuitState.HALF_OPEN:
                # 半开状态成功，检查是否可以关闭
                if self.stats.successful_calls >= self.config.success_threshold:
                    self._transition_to_closed()

    def record_failure(self, error: Exception = None):
        """记录失败"""
        with self._lock:
            self.stats.total_calls += 1
            self.stats.failed_calls += 1
            self.stats.consecutive_failures += 1
            self.stats.last_failure_time = datetime.utcnow()
            self.stats.last_failure_error = str(error) if error else None

            if self.state == CircuitState.HALF_OPEN:
                # 半开状态失败，立即熔断
                self._transition_to_open(error)

            elif self.state == CircuitState.CLOSED:
                # 检查是否达到阈值
                if self.stats.consecutive_failures >= self.config.failure_threshold:
                    self._transition_to_open(error)

    async def call(self, operation: Callable, *args, **kwargs) -> Any:
        """通过熔断器执行操作"""
        if not self.is_call_allowed():
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self.name}' is open",
                circuit_name=self.name,
                stats=self.stats
            )

        try:
            if asyncio.iscoroutinefunction(operation):
                result = await operation(*args, **kwargs)
            else:
                result = operation(*args, **kwargs)

            self.record_success()
            return result

        except Exception as e:
            self.record_failure(e)
            raise

    def reset(self):
        """重置熔断器"""
        with self._lock:
            self.state = CircuitState.CLOSED
            self.stats = CircuitStats()
            self._opened_at = None
            self._half_open_calls = 0

    def get_state(self) -> Dict[str, Any]:
        """获取熔断器状态"""
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "stats": {
                    "total_calls": self.stats.total_calls,
                    "successful_calls": self.stats.successful_calls,
                    "failed_calls": self.stats.failed_calls,
                    "consecutive_failures": self.stats.consecutive_failures,
                    "last_failure_time": self.stats.last_failure_time.isoformat() if self.stats.last_failure_time else None,
                    "last_failure_error": self.stats.last_failure_error,
                },
                "config": {
                    "failure_threshold": self.config.failure_threshold,
                    "success_threshold": self.config.success_threshold,
                    "timeout": self.config.timeout,
                }
            }


class CircuitBreakerOpenError(Exception):
    """熔断器打开异常"""

    def __init__(self, message: str, circuit_name: str, stats: CircuitStats):
        super().__init__(message)
        self.circuit_name = circuit_name
        self.stats = stats


class CircuitBreakerRegistry:
    """熔断器注册表"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._circuits: Dict[str, CircuitBreaker] = {}
        return cls._instance

    def get_or_create(
        self,
        name: str,
        config: CircuitConfig = None
    ) -> CircuitBreaker:
        """获取或创建熔断器"""
        if name not in self._circuits:
            self._circuits[name] = CircuitBreaker(name, config)
        return self._circuits[name]

    def get_all_states(self) -> Dict[str, Dict]:
        """获取所有熔断器状态"""
        return {name: cb.get_state() for name, cb in self._circuits.items()}


# 全局注册表
circuit_registry = CircuitBreakerRegistry()


def circuit_breaker(
    name: str = None,
    failure_threshold: int = 5,
    timeout: float = 30.0
):
    """
    熔断器装饰器

    Usage:
        @circuit_breaker(name="mcp_service", failure_threshold=5)
        async def call_mcp():
            ...
    """
    config = CircuitConfig(
        failure_threshold=failure_threshold,
        timeout=timeout
    )

    def decorator(func: Callable) -> Callable:
        cb_name = name or func.__name__
        cb = circuit_registry.get_or_create(cb_name, config)

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await cb.call(func, *args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not cb.is_call_allowed():
                raise CircuitBreakerOpenError(
                    f"Circuit breaker '{cb_name}' is open",
                    circuit_name=cb_name,
                    stats=cb.stats
                )
            try:
                result = func(*args, **kwargs)
                cb.record_success()
                return result
            except Exception as e:
                cb.record_failure(e)
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
