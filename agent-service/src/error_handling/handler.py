"""增强的错误处理器"""

from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import traceback

from ..observability import get_logger, log_error, log_warning

logger = get_logger(__name__)


class ErrorType(Enum):
    """错误类型"""
    # 数据相关
    PARSE_ERROR = "parse_error"
    DATA_TOO_LARGE = "data_too_large"
    DATA_NOT_FOUND = "data_not_found"
    INVALID_DATA_FORMAT = "invalid_data_format"

    # 工具相关
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_ERROR = "tool_error"
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_RATE_LIMITED = "tool_rate_limited"

    # LLM相关
    LLM_ERROR = "llm_error"
    LLM_RATE_LIMITED = "llm_rate_limited"
    LLM_CONTEXT_TOO_LONG = "llm_context_too_long"

    # 网络相关
    CONNECTION_ERROR = "connection_error"
    TIMEOUT_ERROR = "timeout_error"

    # 业务相关
    INVALID_INPUT = "invalid_input"
    NO_PROBLEM_FOUND = "no_problem_found"
    SESSION_NOT_FOUND = "session_not_found"
    FLOW_NOT_FOUND = "flow_not_found"

    # 系统相关
    INTERNAL_ERROR = "internal_error"
    CIRCUIT_OPEN = "circuit_open"
    UNKNOWN = "unknown"


class ErrorSeverity(Enum):
    """错误严重程度"""
    LOW = "low"           # 可忽略，不影响主流程
    MEDIUM = "medium"     # 需要处理，但可继续
    HIGH = "high"         # 严重，需要中断
    CRITICAL = "critical" # 致命，需要告警


@dataclass
class ErrorContext:
    """错误上下文"""
    operation: str
    session_id: Optional[str] = None
    flow_name: Optional[str] = None
    step_name: Optional[str] = None
    tool_name: Optional[str] = None
    attempt: int = 1
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "operation": self.operation,
            "session_id": self.session_id,
            "flow_name": self.flow_name,
            "step_name": self.step_name,
            "tool_name": self.tool_name,
            "attempt": self.attempt,
            "extra": self.extra,
        }


@dataclass
class HandledError:
    """处理后的错误"""
    error_type: ErrorType
    severity: ErrorSeverity
    message: str
    user_message: str
    recoverable: bool
    action: str
    retry_after: Optional[float] = None
    fallback_available: bool = False
    context: Optional[ErrorContext] = None
    original_error: Optional[Exception] = None
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "error_type": self.error_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "user_message": self.user_message,
            "recoverable": self.recoverable,
            "action": self.action,
            "retry_after": self.retry_after,
            "fallback_available": self.fallback_available,
            "suggestions": self.suggestions,
        }


class ErrorClassifier:
    """错误分类器"""

    # 错误模式匹配规则
    PATTERNS = {
        ErrorType.TIMEOUT_ERROR: ["timeout", "timed out", "deadline exceeded"],
        ErrorType.CONNECTION_ERROR: ["connection", "connect", "network", "unreachable"],
        ErrorType.TOOL_RATE_LIMITED: ["rate limit", "too many requests", "429"],
        ErrorType.LLM_RATE_LIMITED: ["rate limit", "too many requests", "429"],
        ErrorType.DATA_TOO_LARGE: ["too large", "size limit", "exceeds limit"],
        ErrorType.DATA_NOT_FOUND: ["not found", "no data", "does not exist"],
        ErrorType.INVALID_DATA_FORMAT: ["invalid format", "parse error", "malformed"],
        ErrorType.LLM_CONTEXT_TOO_LONG: ["context length", "token limit", "max tokens"],
    }

    # HTTP状态码映射
    STATUS_CODE_MAP = {
        400: ErrorType.INVALID_INPUT,
        401: ErrorType.INTERNAL_ERROR,
        403: ErrorType.INTERNAL_ERROR,
        404: ErrorType.DATA_NOT_FOUND,
        429: ErrorType.TOOL_RATE_LIMITED,
        500: ErrorType.TOOL_ERROR,
        502: ErrorType.CONNECTION_ERROR,
        503: ErrorType.TOOL_ERROR,
        504: ErrorType.TIMEOUT_ERROR,
    }

    @classmethod
    def classify(
        cls,
        error: Exception,
        context: ErrorContext = None
    ) -> ErrorType:
        """分类错误"""
        error_str = str(error).lower()
        error_type_name = type(error).__name__.lower()

        # 检查异常类型
        if "timeout" in error_type_name:
            return ErrorType.TIMEOUT_ERROR
        if "connection" in error_type_name:
            return ErrorType.CONNECTION_ERROR

        # 检查错误消息模式
        for error_type, patterns in cls.PATTERNS.items():
            for pattern in patterns:
                if pattern in error_str:
                    return error_type

        # 检查上下文
        if context:
            if context.tool_name:
                if "rate" in error_str:
                    return ErrorType.TOOL_RATE_LIMITED
                return ErrorType.TOOL_ERROR

            if context.flow_name:
                if "not found" in error_str:
                    return ErrorType.FLOW_NOT_FOUND

        return ErrorType.UNKNOWN


class ErrorHandler:
    """增强的错误处理器"""

    # 错误处理策略
    STRATEGIES = {
        ErrorType.PARSE_ERROR: {
            "severity": ErrorSeverity.MEDIUM,
            "recoverable": False,
            "action": "terminate",
            "user_message": "无法解析数据文件，请检查文件格式是否正确",
            "suggestions": ["检查文件路径是否正确", "确认数据格式支持"],
        },
        ErrorType.DATA_TOO_LARGE: {
            "severity": ErrorSeverity.MEDIUM,
            "recoverable": True,
            "action": "ask_user",
            "user_message": "数据量较大，建议缩小分析范围",
            "suggestions": ["选择特定迭代ID", "指定时间范围"],
        },
        ErrorType.DATA_NOT_FOUND: {
            "severity": ErrorSeverity.MEDIUM,
            "recoverable": False,
            "action": "ask_user",
            "user_message": "未找到指定的数据",
            "suggestions": ["检查数据路径", "确认数据已上传"],
        },
        ErrorType.TOOL_TIMEOUT: {
            "severity": ErrorSeverity.MEDIUM,
            "recoverable": True,
            "action": "retry",
            "user_message": "工具响应超时，正在重试...",
            "retry_after": 5.0,
        },
        ErrorType.TOOL_ERROR: {
            "severity": ErrorSeverity.HIGH,
            "recoverable": True,
            "action": "fallback",
            "user_message": "工具调用失败，尝试备用方案",
        },
        ErrorType.TOOL_RATE_LIMITED: {
            "severity": ErrorSeverity.MEDIUM,
            "recoverable": True,
            "action": "retry",
            "user_message": "请求过于频繁，稍后重试",
            "retry_after": 30.0,
        },
        ErrorType.LLM_ERROR: {
            "severity": ErrorSeverity.HIGH,
            "recoverable": True,
            "action": "fallback",
            "user_message": "AI服务暂时不可用，尝试备用方案",
        },
        ErrorType.LLM_RATE_LIMITED: {
            "severity": ErrorSeverity.MEDIUM,
            "recoverable": True,
            "action": "retry",
            "user_message": "AI服务繁忙，稍后重试",
            "retry_after": 10.0,
        },
        ErrorType.CONNECTION_ERROR: {
            "severity": ErrorSeverity.HIGH,
            "recoverable": True,
            "action": "retry",
            "user_message": "网络连接失败，正在重试...",
            "retry_after": 3.0,
        },
        ErrorType.TIMEOUT_ERROR: {
            "severity": ErrorSeverity.MEDIUM,
            "recoverable": True,
            "action": "retry",
            "user_message": "操作超时，正在重试...",
            "retry_after": 5.0,
        },
        ErrorType.INVALID_INPUT: {
            "severity": ErrorSeverity.LOW,
            "recoverable": False,
            "action": "ask_user",
            "user_message": "输入无效，请检查后重试",
        },
        ErrorType.NO_PROBLEM_FOUND: {
            "severity": ErrorSeverity.LOW,
            "recoverable": False,
            "action": "complete",
            "user_message": "未检测到明显性能问题，您的训练配置看起来很健康 ✓",
        },
        ErrorType.CIRCUIT_OPEN: {
            "severity": ErrorSeverity.HIGH,
            "recoverable": True,
            "action": "fallback",
            "user_message": "服务暂时不可用，请稍后再试",
            "retry_after": 30.0,
        },
        ErrorType.UNKNOWN: {
            "severity": ErrorSeverity.HIGH,
            "recoverable": False,
            "action": "terminate",
            "user_message": "发生未知错误，请稍后重试",
        },
    }

    def __init__(self):
        self._error_counts: Dict[str, int] = {}
        self._last_errors: Dict[str, datetime] = {}

    def handle(
        self,
        error: Exception,
        context: ErrorContext = None,
        error_type: ErrorType = None
    ) -> HandledError:
        """
        处理错误

        Args:
            error: 原始异常
            context: 错误上下文
            error_type: 指定错误类型（可选，默认自动分类）

        Returns:
            处理后的错误信息
        """
        # 分类错误
        if error_type is None:
            error_type = ErrorClassifier.classify(error, context)

        # 获取处理策略
        strategy = self.STRATEGIES.get(error_type, self.STRATEGIES[ErrorType.UNKNOWN])

        # 记录错误
        self._record_error(error_type, context)

        # 构建处理结果
        handled = HandledError(
            error_type=error_type,
            severity=strategy.get("severity", ErrorSeverity.MEDIUM),
            message=str(error),
            user_message=strategy.get("user_message", "发生错误"),
            recoverable=strategy.get("recoverable", False),
            action=strategy.get("action", "terminate"),
            retry_after=strategy.get("retry_after"),
            fallback_available=strategy.get("action") == "fallback",
            context=context,
            original_error=error,
            suggestions=strategy.get("suggestions", []),
        )

        # 记录日志
        self._log_error(handled)

        return handled

    def _record_error(self, error_type: ErrorType, context: ErrorContext):
        """记录错误统计"""
        key = error_type.value
        self._error_counts[key] = self._error_counts.get(key, 0) + 1
        self._last_errors[key] = datetime.utcnow()

    def _log_error(self, handled: HandledError):
        """记录错误日志"""
        log_data = {
            "error_type": handled.error_type.value,
            "severity": handled.severity.value,
            "action": handled.action,
            "recoverable": handled.recoverable,
        }

        if handled.context:
            log_data.update(handled.context.to_dict())

        if handled.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
            log_error(
                f"Critical error: {handled.message}",
                error=handled.original_error,
                **log_data
            )
        else:
            log_warning(f"Error occurred: {handled.message}", **log_data)

    def get_error_stats(self) -> Dict[str, Any]:
        """获取错误统计"""
        return {
            "counts": dict(self._error_counts),
            "last_errors": {
                k: v.isoformat() for k, v in self._last_errors.items()
            },
        }

    def should_retry(self, handled: HandledError, attempt: int, max_attempts: int = 3) -> bool:
        """判断是否应该重试"""
        if not handled.recoverable:
            return False
        if attempt >= max_attempts:
            return False
        if handled.action == "retry":
            return True
        return False

    def get_retry_delay(self, handled: HandledError, attempt: int) -> float:
        """获取重试延迟"""
        base_delay = handled.retry_after or 5.0
        # 指数退避
        return min(base_delay * (2 ** (attempt - 1)), 60.0)


# 全局错误处理器
error_handler = ErrorHandler()
