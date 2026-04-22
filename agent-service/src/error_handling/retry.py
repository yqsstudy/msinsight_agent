"""重试机制 - 指数退避策略"""

import asyncio
import random
from typing import Callable, Any, Optional, List, Type, Tuple
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
import time

from ..observability import get_logger

logger = get_logger(__name__)


class RetryReason(Enum):
    """重试原因"""
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    UNKNOWN = "unknown"


@dataclass
class RetryConfig:
    """重试配置"""
    max_attempts: int = 3
    base_delay: float = 1.0  # 秒
    max_delay: float = 60.0  # 秒
    exponential_base: float = 2.0
    jitter: bool = True  # 添加随机抖动防止惊群
    retryable_exceptions: Tuple[Type[Exception], ...] = (
        TimeoutError,
        ConnectionError,
        ConnectionRefusedError,
    )
    retryable_status_codes: Tuple[int, ...] = (429, 500, 502, 503, 504)


@dataclass
class RetryResult:
    """重试结果"""
    success: bool
    result: Any = None
    error: Optional[Exception] = None
    attempts: int = 0
    total_delay: float = 0.0
    retry_reasons: List[RetryReason] = field(default_factory=list)


class RetryPolicy:
    """重试策略"""

    def __init__(self, config: RetryConfig = None):
        self.config = config or RetryConfig()
        self._attempt_counts: dict = {}  # operation_id -> count

    def calculate_delay(self, attempt: int) -> float:
        """计算重试延迟（指数退避 + 抖动）"""
        delay = min(
            self.config.base_delay * (self.config.exponential_base ** (attempt - 1)),
            self.config.max_delay
        )

        if self.config.jitter:
            # 添加 0-25% 的随机抖动
            jitter = delay * random.uniform(0, 0.25)
            delay = delay + jitter

        return delay

    def should_retry(
        self,
        error: Exception,
        attempt: int,
        status_code: int = None
    ) -> Tuple[bool, RetryReason]:
        """判断是否应该重试"""
        if attempt >= self.config.max_attempts:
            return False, RetryReason.UNKNOWN

        # 检查异常类型
        if isinstance(error, self.config.retryable_exceptions):
            if isinstance(error, TimeoutError):
                return True, RetryReason.TIMEOUT
            elif isinstance(error, (ConnectionError, ConnectionRefusedError)):
                return True, RetryReason.CONNECTION_ERROR
            return True, RetryReason.UNKNOWN

        # 检查状态码
        if status_code:
            if status_code == 429:
                return True, RetryReason.RATE_LIMIT
            elif status_code in self.config.retryable_status_codes:
                return True, RetryReason.SERVER_ERROR

        # 检查错误消息
        error_str = str(error).lower()
        if "timeout" in error_str:
            return True, RetryReason.TIMEOUT
        elif "rate limit" in error_str or "too many" in error_str:
            return True, RetryReason.RATE_LIMIT
        elif "connection" in error_str:
            return True, RetryReason.CONNECTION_ERROR

        return False, RetryReason.UNKNOWN

    async def execute_with_retry(
        self,
        operation: Callable,
        operation_id: str = None,
        *args,
        **kwargs
    ) -> RetryResult:
        """执行操作并在失败时重试"""
        result = RetryResult(success=False)
        attempt = 0

        while attempt < self.config.max_attempts:
            attempt += 1
            result.attempts = attempt

            try:
                # 执行操作
                if asyncio.iscoroutinefunction(operation):
                    output = await operation(*args, **kwargs)
                else:
                    output = operation(*args, **kwargs)

                result.success = True
                result.result = output

                if attempt > 1:
                    logger.info(f"Operation succeeded after {attempt} attempts: operation_id={operation_id}")

                return result

            except Exception as e:
                result.error = e

                # 判断是否重试
                should_retry, reason = self.should_retry(e, attempt)
                result.retry_reasons.append(reason)

                if not should_retry:
                    logger.error(f"Operation failed, not retryable: operation_id={operation_id}, error={str(e)}, attempt={attempt}")
                    return result

                # 计算延迟
                delay = self.calculate_delay(attempt)
                result.total_delay += delay

                logger.warning(f"Operation failed, retrying: operation_id={operation_id}, error={str(e)}, attempt={attempt}, delay={delay}, reason={reason.value}")

                # 等待后重试
                await asyncio.sleep(delay)

        return result


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = None,
    operation_id: str = None
):
    """
    重试装饰器

    Usage:
        @retry(max_attempts=3, base_delay=1.0)
        async def my_operation():
            ...
    """
    config = RetryConfig(
        max_attempts=max_attempts,
        base_delay=base_delay,
    )
    if retryable_exceptions:
        config.retryable_exceptions = retryable_exceptions

    policy = RetryPolicy(config)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            op_id = operation_id or func.__name__
            result = await policy.execute_with_retry(func, op_id, *args, **kwargs)
            if result.success:
                return result.result
            raise result.error

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            op_id = operation_id or func.__name__
            # 同步版本
            attempt = 0
            last_error = None
            while attempt < max_attempts:
                attempt += 1
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    should_retry, _ = policy.should_retry(e, attempt)
                    if not should_retry:
                        raise
                    delay = policy.calculate_delay(attempt)
                    time.sleep(delay)
            raise last_error

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
