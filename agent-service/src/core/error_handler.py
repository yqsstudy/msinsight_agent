"""异常处理器"""

from typing import Dict, Any, Optional, Callable
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ErrorType(Enum):
    """错误类型"""
    PARSE_ERROR = "parse_error"           # 数据解析失败
    TOOL_TIMEOUT = "tool_timeout"         # 工具调用超时
    TOOL_ERROR = "tool_error"             # 工具调用失败
    DATA_TOO_LARGE = "data_too_large"     # 数据量过大
    INVALID_INPUT = "invalid_input"       # 用户输入无效
    NO_PROBLEM_FOUND = "no_problem_found" # 未发现问题
    UNKNOWN = "unknown"                   # 未知错误


class ErrorHandler:
    """异常处理器"""

    # 错误消息模板
    ERROR_MESSAGES = {
        ErrorType.PARSE_ERROR: "无法解析该文件，请确认：\n1) 文件路径正确\n2) 数据格式支持",
        ErrorType.TOOL_TIMEOUT: "分析工具响应较慢，正在重试...",
        ErrorType.TOOL_ERROR: "分析工具调用失败",
        ErrorType.DATA_TOO_LARGE: "数据量较大，建议先选择特定迭代ID进行分析",
        ErrorType.INVALID_INPUT: "输入无效，请检查后重试",
        ErrorType.NO_PROBLEM_FOUND: "未检测到明显性能问题，您的训练配置看起来很健康 ✓",
        ErrorType.UNKNOWN: "发生未知错误，请稍后重试",
    }

    # 重试配置
    MAX_RETRIES = 1
    RETRY_DELAY = 1.0  # 秒

    def __init__(self):
        self._retry_count: Dict[str, int] = {}

    def handle(
        self,
        error_type: ErrorType,
        context: Dict[str, Any] = None,
        original_error: Exception = None
    ) -> Dict[str, Any]:
        """
        处理错误

        Args:
            error_type: 错误类型
            context: 上下文信息
            original_error: 原始异常

        Returns:
            处理结果，包含用户提示和后续动作
        """
        context = context or {}

        # 记录日志
        logger.error(
            f"Error occurred: {error_type.value}",
            extra={"context": context, "original_error": str(original_error)}
        )

        # 获取用户提示
        user_message = self.ERROR_MESSAGES.get(error_type, self.ERROR_MESSAGES[ErrorType.UNKNOWN])

        # 根据错误类型决定处理策略
        result = {
            "error_type": error_type.value,
            "user_message": user_message,
            "recoverable": self._is_recoverable(error_type),
            "action": self._get_action(error_type),
        }

        # 添加额外信息
        if error_type == ErrorType.TOOL_ERROR and original_error:
            result["details"] = str(original_error)

        return result

    def _is_recoverable(self, error_type: ErrorType) -> bool:
        """判断错误是否可恢复"""
        recoverable_types = {
            ErrorType.TOOL_TIMEOUT,
            ErrorType.INVALID_INPUT,
        }
        return error_type in recoverable_types

    def _get_action(self, error_type: ErrorType) -> str:
        """获取后续动作"""
        actions = {
            ErrorType.PARSE_ERROR: "terminate",
            ErrorType.TOOL_TIMEOUT: "retry",
            ErrorType.TOOL_ERROR: "fallback",
            ErrorType.DATA_TOO_LARGE: "ask_user",
            ErrorType.INVALID_INPUT: "ask_retry",
            ErrorType.NO_PROBLEM_FOUND: "complete",
            ErrorType.UNKNOWN: "terminate",
        }
        return actions.get(error_type, "terminate")

    def should_retry(self, operation_id: str) -> bool:
        """判断是否应该重试"""
        current_count = self._retry_count.get(operation_id, 0)
        return current_count < self.MAX_RETRIES

    def record_retry(self, operation_id: str):
        """记录重试"""
        self._retry_count[operation_id] = self._retry_count.get(operation_id, 0) + 1

    def reset_retry(self, operation_id: str):
        """重置重试计数"""
        self._retry_count.pop(operation_id, None)

    def classify_error(self, error: Exception) -> ErrorType:
        """分类错误"""
        error_str = str(error).lower()

        if "timeout" in error_str:
            return ErrorType.TOOL_TIMEOUT
        elif "parse" in error_str or "format" in error_str:
            return ErrorType.PARSE_ERROR
        elif "not found" in error_str or "no data" in error_str:
            return ErrorType.NO_PROBLEM_FOUND
        elif "too large" in error_str or "limit" in error_str:
            return ErrorType.DATA_TOO_LARGE
        elif "invalid" in error_str:
            return ErrorType.INVALID_INPUT
        else:
            return ErrorType.UNKNOWN
