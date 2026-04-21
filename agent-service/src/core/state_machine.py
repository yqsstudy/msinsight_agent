"""分析状态机 - 管理分析流程状态"""

from typing import Dict, Tuple, Optional, Any
from enum import Enum


class State(Enum):
    """分析状态"""
    IDLE = "IDLE"                  # 空闲
    PARSING = "PARSING"            # 解析数据中
    DETECTING = "DETECTING"        # 检测问题类型中
    WAITING_INPUT = "WAITING_INPUT"  # 等待用户输入
    ANALYZING = "ANALYZING"        # 分析执行中
    REPORTING = "REPORTING"        # 生成报告中
    COMPLETED = "COMPLETED"        # 完成
    ERROR = "ERROR"                # 错误状态


class Event(Enum):
    """状态转换事件"""
    START = "start"
    PARSE_SUCCESS = "parse_success"
    PARSE_ERROR = "parse_error"
    DETECT_NEED_INPUT = "detect_need_input"
    DETECT_PROCEED = "detect_proceed"
    INPUT_RECEIVED = "input_received"
    ANALYZE_SUCCESS = "analyze_success"
    ANALYZE_ERROR = "analyze_error"
    REPORT_SUCCESS = "report_success"
    REPORT_ERROR = "report_error"
    RESET = "reset"
    CONTINUE = "continue"


class AnalysisStateMachine:
    """分析流程状态机"""

    # 状态转换表: (当前状态, 事件) -> 新状态
    TRANSITIONS: Dict[Tuple[State, Event], State] = {
        (State.IDLE, Event.START): State.PARSING,

        (State.PARSING, Event.PARSE_SUCCESS): State.DETECTING,
        (State.PARSING, Event.PARSE_ERROR): State.ERROR,

        (State.DETECTING, Event.DETECT_NEED_INPUT): State.WAITING_INPUT,
        (State.DETECTING, Event.DETECT_PROCEED): State.ANALYZING,
        (State.DETECTING, Event.ANALYZE_ERROR): State.ERROR,

        (State.WAITING_INPUT, Event.INPUT_RECEIVED): State.ANALYZING,

        (State.ANALYZING, Event.ANALYZE_SUCCESS): State.REPORTING,
        (State.ANALYZING, Event.ANALYZE_ERROR): State.ERROR,

        (State.REPORTING, Event.REPORT_SUCCESS): State.COMPLETED,
        (State.REPORTING, Event.REPORT_ERROR): State.ERROR,

        # 任意状态都可以重置
        (State.ERROR, Event.RESET): State.IDLE,
        (State.COMPLETED, Event.RESET): State.IDLE,

        # 继续分析
        (State.IDLE, Event.CONTINUE): State.ANALYZING,
    }

    def __init__(self):
        self.current_state = State.IDLE
        self.context: Dict[str, Any] = {}
        self._state_history: list = [(State.IDLE, None)]

    @property
    def state(self) -> str:
        """获取当前状态名称"""
        return self.current_state.value

    def transition(self, event: Event) -> Tuple[bool, str]:
        """
        状态转换

        Args:
            event: 触发事件

        Returns:
            Tuple[bool, str]: (是否成功, 新状态名称)
        """
        key = (self.current_state, event)
        if key in self.TRANSITIONS:
            old_state = self.current_state
            self.current_state = self.TRANSITIONS[key]
            self._state_history.append((self.current_state, event))
            return True, self.current_state.value
        return False, self.current_state.value

    def can_transition(self, event: Event) -> bool:
        """检查是否可以进行状态转换"""
        return (self.current_state, event) in self.TRANSITIONS

    def is_idle(self) -> bool:
        return self.current_state == State.IDLE

    def is_waiting_input(self) -> bool:
        return self.current_state == State.WAITING_INPUT

    def is_completed(self) -> bool:
        return self.current_state == State.COMPLETED

    def is_error(self) -> bool:
        return self.current_state == State.ERROR

    def is_analyzing(self) -> bool:
        return self.current_state in (State.PARSING, State.DETECTING, State.ANALYZING)

    def reset(self):
        """重置状态机"""
        self.current_state = State.IDLE
        self.context = {}
        self._state_history = [(State.IDLE, None)]

    def set_context(self, key: str, value: Any):
        """设置上下文数据"""
        self.context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        """获取上下文数据"""
        return self.context.get(key, default)

    def get_history(self) -> list:
        """获取状态历史"""
        return [(s.value, e.value if e else None) for s, e in self._state_history]

    def get_valid_events(self) -> list:
        """获取当前状态下有效的事件"""
        valid_events = []
        for (state, event) in self.TRANSITIONS:
            if state == self.current_state:
                valid_events.append(event.value)
        return valid_events
