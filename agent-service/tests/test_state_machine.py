"""测试状态机"""

import pytest
from src.core.state_machine import AnalysisStateMachine, State, Event


class TestStateMachine:

    def test_initial_state(self):
        """测试初始状态"""
        sm = AnalysisStateMachine()
        assert sm.current_state == State.IDLE
        assert sm.state == "IDLE"

    def test_valid_transition(self):
        """测试有效状态转换"""
        sm = AnalysisStateMachine()

        # IDLE -> PARSING
        success, new_state = sm.transition(Event.START)
        assert success
        assert new_state == "PARSING"
        assert sm.current_state == State.PARSING

    def test_invalid_transition(self):
        """测试无效状态转换"""
        sm = AnalysisStateMachine()

        # IDLE状态下，PARSE_SUCCESS是无效事件
        success, new_state = sm.transition(Event.PARSE_SUCCESS)
        assert not success
        assert sm.current_state == State.IDLE

    def test_full_flow(self):
        """测试完整流程"""
        sm = AnalysisStateMachine()

        # IDLE -> PARSING
        sm.transition(Event.START)
        assert sm.current_state == State.PARSING

        # PARSING -> DETECTING
        sm.transition(Event.PARSE_SUCCESS)
        assert sm.current_state == State.DETECTING

        # DETECTING -> ANALYZING
        sm.transition(Event.DETECT_PROCEED)
        assert sm.current_state == State.ANALYZING

        # ANALYZING -> REPORTING
        sm.transition(Event.ANALYZE_SUCCESS)
        assert sm.current_state == State.REPORTING

        # REPORTING -> COMPLETED
        sm.transition(Event.REPORT_SUCCESS)
        assert sm.current_state == State.COMPLETED

    def test_error_state(self):
        """测试错误状态"""
        sm = AnalysisStateMachine()

        sm.transition(Event.START)
        sm.transition(Event.PARSE_ERROR)

        assert sm.current_state == State.ERROR
        assert sm.is_error()

    def test_waiting_input_state(self):
        """测试等待输入状态"""
        sm = AnalysisStateMachine()

        sm.transition(Event.START)
        sm.transition(Event.PARSE_SUCCESS)
        sm.transition(Event.DETECT_NEED_INPUT)

        assert sm.current_state == State.WAITING_INPUT
        assert sm.is_waiting_input()

    def test_reset(self):
        """测试重置"""
        sm = AnalysisStateMachine()

        sm.transition(Event.START)
        sm.transition(Event.PARSE_ERROR)
        sm.reset()

        assert sm.current_state == State.IDLE
        assert sm.context == {}

    def test_context(self):
        """测试上下文"""
        sm = AnalysisStateMachine()

        sm.set_context("data_path", "/path/to/data")
        sm.set_context("data_id", "123")

        assert sm.get_context("data_path") == "/path/to/data"
        assert sm.get_context("data_id") == "123"
        assert sm.get_context("nonexistent", "default") == "default"

    def test_valid_events(self):
        """测试获取有效事件"""
        sm = AnalysisStateMachine()

        valid_events = sm.get_valid_events()
        assert "start" in valid_events

        sm.transition(Event.START)
        valid_events = sm.get_valid_events()
        assert "parse_success" in valid_events
        assert "parse_error" in valid_events
