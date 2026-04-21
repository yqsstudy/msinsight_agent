"""DAG引擎 - 轻量级工作流编排引擎"""

import asyncio
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Callable, Union
import uuid

import yaml


class StepType(Enum):
    """步骤类型"""
    MCP_TOOL = "mcp_tool"
    INTERNAL = "internal"
    DECISION = "decision"
    CONDITION = "condition"
    PARALLEL = "parallel"
    REPORT = "report"
    USER_INPUT = "user_input"
    TERMINAL = "terminal"


class StepStatus(Enum):
    """步骤状态"""
    PENDING = "pending"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    """步骤执行结果"""
    step_name: str
    status: StepStatus
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    need_input: bool = False
    question: Optional[str] = None
    options: Optional[List[Dict]] = None
    reason: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "step_name": self.step_name,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "need_input": self.need_input,
            "question": self.question,
            "options": self.options,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class FlowContext:
    """流程上下文"""
    flow_name: str
    session_id: str
    input: Dict[str, Any] = field(default_factory=dict)
    state: Dict[str, Any] = field(default_factory=dict)
    history: List[StepResult] = field(default_factory=list)
    current_step: Optional[str] = None
    status: str = "pending"

    def set_state(self, key: str, value: Any):
        """设置状态"""
        self.state[key] = value

    def get_state(self, key: str, default: Any = None) -> Any:
        """获取状态"""
        return self.state.get(key, default)

    def add_history(self, result: StepResult):
        """添加历史记录"""
        self.history.append(result)

    def to_dict(self) -> dict:
        return {
            "flow_name": self.flow_name,
            "session_id": self.session_id,
            "input": self.input,
            "state": self.state,
            "current_step": self.current_step,
            "status": self.status,
            "history": [h.to_dict() for h in self.history]
        }


class ExpressionEvaluator:
    """表达式求值器"""

    @staticmethod
    def evaluate(expression: str, context: FlowContext) -> Any:
        """
        求值表达式

        支持的表达式:
        - ${input.xxx} - 输入参数
        - ${state.xxx} - 状态值
        - ${step_name.output_field} - 步骤输出
        - len(${state.xxx}) - 函数调用
        """
        # 替换变量
        def replace_var(match):
            var_path = match.group(1)
            return str(ExpressionEvaluator._resolve_path(var_path, context))

        # 处理函数调用
        if expression.startswith("len("):
            inner = expression[4:-1]
            value = ExpressionEvaluator.evaluate(inner, context)
            if isinstance(value, (list, dict, str)):
                return len(value)
            return 0

        # 处理比较表达式
        if " not in " in expression:
            parts = expression.split(" not in ")
            left = ExpressionEvaluator.evaluate(parts[0].strip(), context)
            right = ExpressionEvaluator.evaluate(parts[1].strip(), context)
            return left not in right

        if " in " in expression:
            parts = expression.split(" in ")
            left = ExpressionEvaluator.evaluate(parts[0].strip(), context)
            right = ExpressionEvaluator.evaluate(parts[1].strip(), context)
            return left in right

        # 处理简单变量
        if expression.startswith("${") and expression.endswith("}"):
            var_path = expression[2:-1]
            return ExpressionEvaluator._resolve_path(var_path, context)

        # 处理包含变量的字符串
        result = re.sub(r'\$\{([^}]+)\}', replace_var, expression)
        return result

    @staticmethod
    def _resolve_path(path: str, context: FlowContext) -> Any:
        """解析路径"""
        parts = path.split(".")
        if parts[0] == "input":
            value = context.input
            parts = parts[1:]
        elif parts[0] == "state":
            value = context.state
            parts = parts[1:]
        else:
            # 从历史记录中查找步骤输出
            step_name = parts[0]
            for h in context.history:
                if h.step_name == step_name:
                    value = h.output
                    parts = parts[1:]
                    break
            else:
                return None

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None

        return value


class DAGConfig:
    """DAG配置加载器"""

    def __init__(self, config_path: str = "./config/flows.yaml"):
        self.config_path = config_path
        self._config: Dict[str, Any] = {}
        self._load()

    def _load(self):
        """加载配置"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            self._config = {"flows": {}, "handlers": {}, "rules": {}}

    def get_flow(self, flow_name: str) -> Optional[Dict[str, Any]]:
        """获取流程定义"""
        return self._config.get("flows", {}).get(flow_name)

    def get_handler(self, handler_name: str) -> Optional[Dict[str, Any]]:
        """获取处理器定义"""
        return self._config.get("handlers", {}).get(handler_name)

    def get_rules(self, rule_type: str) -> List[Dict[str, Any]]:
        """获取规则"""
        return self._config.get("rules", {}).get(rule_type, [])

    def list_flows(self) -> List[str]:
        """列出所有流程"""
        return list(self._config.get("flows", {}).keys())

    def reload(self):
        """重新加载配置"""
        self._load()
