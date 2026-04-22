"""测试意图识别器"""

import pytest
from src.core.intent_recognizer import IntentRecognizer, IntentType


class TestIntentRecognizer:

    def setup_method(self):
        self.recognizer = IntentRecognizer()

    def test_full_analysis_intent(self):
        """测试全量分析意图"""
        intent = self.recognizer.recognize("帮我分析 /path/to/data")
        assert intent.type == IntentType.FULL_ANALYSIS
        assert intent.data_path == "/path/to/data"

    def test_targeted_analysis_intent(self):
        """测试定向分析意图"""
        intent = self.recognizer.recognize("帮我分析 /path/to/data 的内存问题")
        assert intent.type == IntentType.TARGETED_ANALYSIS
        assert intent.data_path == "/path/to/data"
        assert intent.target_problem == "memory"

    def test_communication_analysis(self):
        """测试通信问题识别"""
        intent = self.recognizer.recognize("分析 /data/path 的通信瓶颈")
        assert intent.type == IntentType.TARGETED_ANALYSIS
        assert intent.target_problem == "communication"

    def test_continue_intent(self):
        """测试继续意图"""
        intent = self.recognizer.recognize("继续上次的分析")
        assert intent.type == IntentType.CONTINUE

    def test_feedback_intent(self):
        """测试反馈意图"""
        intent = self.recognizer.recognize("采纳这个建议")
        assert intent.type == IntentType.FEEDBACK

    def test_question_intent(self):
        """测试一般问题意图"""
        intent = self.recognizer.recognize("什么是慢卡分析？")
        assert intent.type == IntentType.QUESTION

    def test_choice_with_digit(self):
        """测试数字选择"""
        options = [
            {"value": "world_group", "label": "World Group"},
            {"value": "tp_group", "label": "TP Group"}
        ]
        intent = self.recognizer.recognize("1", {"state": "WAITING_INPUT", "pending_choices": options})
        assert intent.type == IntentType.CHOICE
        assert intent.choice == "world_group"

    def test_choice_with_label(self):
        """测试标签选择"""
        options = [
            {"value": "world_group", "label": "World Group"},
            {"value": "tp_group", "label": "TP Group"}
        ]
        intent = self.recognizer.recognize("TP Group", {"state": "WAITING_INPUT", "pending_choices": options})
        assert intent.type == IntentType.CHOICE
        assert intent.choice == "tp_group"

    def test_problem_type_detection(self):
        """测试问题类型检测"""
        assert self.recognizer._detect_problem_type("内存问题") == "memory"
        assert self.recognizer._detect_problem_type("通信瓶颈") == "communication"
        assert self.recognizer._detect_problem_type("OOM") == "memory"  # OOM needs to be exact match
        assert self.recognizer._detect_problem_type("一般问题") is None

    def test_path_extraction(self):
        """测试路径提取"""
        assert self.recognizer._extract_path("分析 /home/user/data") == "/home/user/data"
        assert self.recognizer._extract_path("路径是 C:\\Users\\data") == "C:\\Users\\data"
        assert self.recognizer._extract_path("没有路径") is None
