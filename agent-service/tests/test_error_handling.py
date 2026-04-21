"""错误处理模块测试"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from src.error_handling import (
    RetryPolicy,
    RetryConfig,
    CircuitBreaker,
    CircuitConfig,
    CircuitState,
    ErrorHandler,
    ErrorType,
    ErrorContext,
    FallbackManager,
    FallbackStrategy,
    FallbackConfig,
    FallbackType,
    circuit_registry,
)


class TestRetryPolicy:
    """重试策略测试"""

    def test_calculate_delay(self):
        """测试延迟计算"""
        config = RetryConfig(base_delay=1.0, max_delay=60.0)
        policy = RetryPolicy(config)

        # 第一次重试
        delay1 = policy.calculate_delay(1)
        assert delay1 >= 1.0

        # 第二次重试（指数增长）
        delay2 = policy.calculate_delay(2)
        assert delay2 > delay1

        # 不超过最大延迟（考虑抖动）
        delay10 = policy.calculate_delay(10)
        assert delay10 <= 75.0  # 60.0 + 25% jitter

    def test_should_retry_timeout(self):
        """测试超时错误重试"""
        policy = RetryPolicy()

        should, reason = policy.should_retry(TimeoutError("timeout"), 1)
        assert should is True

    def test_should_retry_max_attempts(self):
        """测试最大重试次数"""
        policy = RetryPolicy(RetryConfig(max_attempts=3))

        should, _ = policy.should_retry(TimeoutError("timeout"), 3)
        assert should is False

    @pytest.mark.asyncio
    async def test_execute_with_retry_success(self):
        """测试重试成功"""
        policy = RetryPolicy(RetryConfig(max_attempts=3))

        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TimeoutError("timeout")
            return "success"

        result = await policy.execute_with_retry(operation, "test_op")

        assert result.success is True
        assert result.result == "success"
        assert result.attempts == 2


class TestCircuitBreaker:
    """熔断器测试"""

    def setup_method(self):
        """每个测试前重置"""
        self.cb = CircuitBreaker(
            "test_circuit",
            CircuitConfig(failure_threshold=3, timeout=5.0)
        )

    def test_initial_state_closed(self):
        """测试初始状态为关闭"""
        assert self.cb.state == CircuitState.CLOSED
        assert self.cb.is_call_allowed() is True

    def test_open_after_threshold(self):
        """测试达到阈值后熔断"""
        for _ in range(3):
            self.cb.record_failure(Exception("error"))

        assert self.cb.state == CircuitState.OPEN
        assert self.cb.is_call_allowed() is False

    def test_close_after_success_in_half_open(self):
        """测试半开状态成功后关闭"""
        # 先打开熔断器
        for _ in range(3):
            self.cb.record_failure(Exception("error"))

        assert self.cb.state == CircuitState.OPEN

        # 模拟超时后进入半开
        self.cb._opened_at = None  # 强制允许重置
        assert self.cb.is_call_allowed() is True
        assert self.cb.state == CircuitState.HALF_OPEN

        # 记录成功
        for _ in range(3):
            self.cb.record_success()

        assert self.cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_call_through_circuit(self):
        """测试通过熔断器调用"""
        async def success_operation():
            return "ok"

        result = await self.cb.call(success_operation)
        assert result == "ok"
        assert self.cb.stats.successful_calls == 1

    @pytest.mark.asyncio
    async def test_call_blocked_when_open(self):
        """测试熔断时阻止调用"""
        # 打开熔断器
        for _ in range(3):
            self.cb.record_failure(Exception("error"))

        with pytest.raises(Exception) as exc_info:
            await self.cb.call(lambda: "ok")

        assert "open" in str(exc_info.value).lower()


class TestErrorHandler:
    """错误处理器测试"""

    def setup_method(self):
        self.handler = ErrorHandler()

    def test_classify_timeout_error(self):
        """测试超时错误分类"""
        ctx = ErrorContext(operation="test")
        error_type = self.handler.handle(TimeoutError("timeout"), ctx).error_type
        assert error_type == ErrorType.TIMEOUT_ERROR

    def test_classify_connection_error(self):
        """测试连接错误分类"""
        ctx = ErrorContext(operation="test")
        error_type = self.handler.handle(ConnectionError("connection failed"), ctx).error_type
        assert error_type == ErrorType.CONNECTION_ERROR

    def test_handle_recoverable_error(self):
        """测试可恢复错误"""
        ctx = ErrorContext(operation="test", tool_name="parse_data")
        handled = self.handler.handle(TimeoutError("timeout"), ctx)

        assert handled.recoverable is True
        assert handled.action == "retry"

    def test_handle_non_recoverable_error(self):
        """测试不可恢复错误"""
        ctx = ErrorContext(operation="test")
        handled = self.handler.handle(ValueError("invalid input"), ctx)

        assert handled.recoverable is False

    def test_error_stats(self):
        """测试错误统计"""
        ctx = ErrorContext(operation="test")

        self.handler.handle(TimeoutError("timeout"), ctx)
        self.handler.handle(TimeoutError("timeout"), ctx)
        self.handler.handle(ConnectionError("connection"), ctx)

        stats = self.handler.get_error_stats()
        assert stats["counts"]["timeout_error"] == 2
        assert stats["counts"]["connection_error"] == 1


class TestFallbackStrategy:
    """降级策略测试"""

    def test_default_value_fallback(self):
        """测试默认值降级"""
        config = FallbackConfig(
            fallback_type=FallbackType.DEFAULT_VALUE,
            default_value={"result": "default"}
        )
        strategy = FallbackStrategy("test", config)

        result = asyncio.run(strategy.execute())
        assert result == {"result": "default"}

    def test_graceful_degradation(self):
        """测试优雅降级"""
        config = FallbackConfig(
            fallback_type=FallbackType.GRACEFUL_DEGRADATION,
            default_value={"data": None},
            message="服务降级"
        )
        strategy = FallbackStrategy("test", config)

        result = asyncio.run(strategy.execute())
        assert result["degraded"] is True
        assert result["message"] == "服务降级"


class TestFallbackManager:
    """降级管理器测试"""

    def test_register_and_get(self):
        """测试注册和获取"""
        manager = FallbackManager()
        strategy = FallbackStrategy("test", FallbackConfig(FallbackType.DEFAULT_VALUE))

        manager.register("test_strategy", strategy)
        retrieved = manager.get("test_strategy")

        assert retrieved is strategy

    @pytest.mark.asyncio
    async def test_execute_fallback(self):
        """测试执行降级"""
        manager = FallbackManager()
        config = FallbackConfig(
            fallback_type=FallbackType.DEFAULT_VALUE,
            default_value={"fallback": True}
        )
        strategy = FallbackStrategy("test", config)
        manager.register("test", strategy)

        result = await manager.execute_fallback("test", Exception("error"))

        assert result == {"fallback": True}
