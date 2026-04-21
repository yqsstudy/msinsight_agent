"""日志配置 - 结构化日志"""

import logging
import sys
import json
from datetime import datetime
from typing import Any, Dict, Optional
from pathlib import Path
import uuid
from contextvars import ContextVar

# 上下文变量，用于追踪请求
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
session_id_var: ContextVar[str] = ContextVar("session_id", default="")


class JSONFormatter(logging.Formatter):
    """JSON格式日志格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加上下文信息
        request_id = request_id_var.get()
        if request_id:
            log_data["request_id"] = request_id

        session_id = session_id_var.get()
        if session_id:
            log_data["session_id"] = session_id

        # 添加额外字段
        if hasattr(record, "extra") and record.extra:
            log_data["extra"] = record.extra

        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


class HumanFormatter(logging.Formatter):
    """人类可读格式日志格式化器（开发模式）"""

    def format(self, record: logging.LogRecord) -> str:
        # 时间戳
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        # 基础信息
        base = f"[{timestamp}] [{record.levelname:5}] [{record.name}] {record.getMessage()}"

        # 上下文
        context_parts = []
        request_id = request_id_var.get()
        if request_id:
            context_parts.append(f"req={request_id[:8]}")
        session_id = session_id_var.get()
        if session_id:
            context_parts.append(f"sid={session_id[:8]}")

        if context_parts:
            base = f"[{' '.join(context_parts)}] {base}"

        # 额外字段
        if hasattr(record, "extra") and record.extra:
            extra_str = " ".join(f"{k}={v}" for k, v in record.extra.items())
            base = f"{base} | {extra_str}"

        # 异常
        if record.exc_info:
            base = f"{base}\n{self.formatException(record.exc_info)}"

        return base


class LoggerAdapter(logging.LoggerAdapter):
    """日志适配器，支持额外字段"""

    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        if hasattr(self, "extra"):
            extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    log_file: Optional[str] = None
) -> None:
    """
    配置日志

    Args:
        level: 日志级别
        json_format: 是否使用JSON格式
        log_file: 日志文件路径（可选）
    """
    # 获取根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # 清除现有处理器
    root_logger.handlers.clear()

    # 选择格式化器
    formatter = JSONFormatter() if json_format else HumanFormatter()

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 文件处理器
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(JSONFormatter())  # 文件始终用JSON格式
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """获取日志器"""
    return logging.getLogger(name)


def set_request_id(request_id: Optional[str] = None) -> str:
    """设置请求ID"""
    if request_id is None:
        request_id = str(uuid.uuid4())
    request_id_var.set(request_id)
    return request_id


def set_session_id(session_id: str) -> None:
    """设置会话ID"""
    session_id_var.set(session_id)


def clear_context() -> None:
    """清除上下文"""
    request_id_var.set("")
    session_id_var.set("")


class LogContext:
    """日志上下文管理器"""

    def __init__(
        self,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None
    ):
        self.request_id = request_id or str(uuid.uuid4())
        self.session_id = session_id or ""
        self._old_request_id = None
        self._old_session_id = None

    def __enter__(self):
        self._old_request_id = request_id_var.get()
        self._old_session_id = session_id_var.get()
        request_id_var.set(self.request_id)
        if self.session_id:
            session_id_var.set(self.session_id)
        return self

    def __exit__(self, *args):
        request_id_var.set(self._old_request_id)
        session_id_var.set(self._old_session_id)


# 便捷函数
def log_info(message: str, **kwargs):
    """记录INFO日志"""
    logger = get_logger("app")
    logger.info(message, extra={"extra": kwargs} if kwargs else {})


def log_error(message: str, error: Optional[Exception] = None, **kwargs):
    """记录ERROR日志"""
    logger = get_logger("app")
    if error:
        logger.error(message, exc_info=error, extra={"extra": kwargs} if kwargs else {})
    else:
        logger.error(message, extra={"extra": kwargs} if kwargs else {})


def log_warning(message: str, **kwargs):
    """记录WARNING日志"""
    logger = get_logger("app")
    logger.warning(message, extra={"extra": kwargs} if kwargs else {})


def log_debug(message: str, **kwargs):
    """记录DEBUG日志"""
    logger = get_logger("app")
    logger.debug(message, extra={"extra": kwargs} if kwargs else {})
