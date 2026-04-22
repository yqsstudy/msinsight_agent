"""意图识别器 - 识别用户意图"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List
import re


class IntentType(Enum):
    """意图类型"""
    FULL_ANALYSIS = "full_analysis"          # 全量分析
    TARGETED_ANALYSIS = "targeted_analysis"  # 定向分析
    CONTINUE = "continue"                    # 继续上次分析
    FEEDBACK = "feedback"                    # 反馈/采纳建议
    QUESTION = "question"                    # 一般性问题
    CHOICE = "choice"                        # 用户选择
    UNKNOWN = "unknown"                      # 未知意图


@dataclass
class Intent:
    """用户意图"""
    type: IntentType
    target_problem: Optional[str] = None  # 定向分析时的问题类型
    data_path: Optional[str] = None       # 数据路径
    choice: Optional[str] = None          # 用户选择
    adopted: Optional[bool] = None        # 反馈是否采纳
    comment: Optional[str] = None         # 反馈评论
    confidence: float = 1.0


class IntentRecognizer:
    """识别用户意图"""

    # 问题类型关键词映射
    PROBLEM_KEYWORDS = {
        "memory": ["内存", "memory", "OOM", "显存", "内存泄漏", "memory leak"],
        "communication": ["通信", "communication", "慢卡", "slow card", "网络", "network", "带宽", "bandwidth"],
        "compute": ["计算", "compute", "GPU", "算力", "计算瓶颈"],
        "io": ["IO", "读写", "磁盘", "disk", "存储", "storage"],
    }

    # 数据路径模式
    PATH_PATTERNS = [
        r'/[\w/\-\.]+',      # Unix路径
        r'[A-Za-z]:\\[\w\\\-\.]+',  # Windows路径
        r'file://[\w/\-\.]+',  # file协议
    ]

    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM客户端，用于复杂意图识别
        """
        self.llm_client = llm_client

    def recognize(self, message: str, context: dict = None) -> Intent:
        """
        识别用户意图

        Args:
            message: 用户消息
            context: 对话上下文（包含当前状态等）

        Returns:
            Intent: 识别出的意图
        """
        context = context or {}
        current_state = context.get("state", "IDLE")
        pending_choices = context.get("pending_choices", [])

        # 如果当前状态是等待用户输入，检查是否是选择
        if current_state == "WAITING_INPUT" and pending_choices:
            choice_intent = self._try_parse_choice(message, pending_choices)
            if choice_intent:
                return choice_intent

        # 检查是否是反馈
        if self._is_feedback(message):
            return self._parse_feedback(message)

        # 检查是否包含数据路径
        data_path = self._extract_path(message)

        # 检查问题类型
        target_problem = self._detect_problem_type(message)

        # 判断意图类型
        if data_path:
            if target_problem:
                return Intent(
                    type=IntentType.TARGETED_ANALYSIS,
                    target_problem=target_problem,
                    data_path=data_path
                )
            else:
                return Intent(
                    type=IntentType.FULL_ANALYSIS,
                    data_path=data_path
                )

        # 检查是否是继续分析
        if self._is_continue_request(message):
            return Intent(type=IntentType.CONTINUE)

        # 默认作为一般问题处理
        return Intent(type=IntentType.QUESTION)

    def _try_parse_choice(self, message: str, options: list) -> Optional[Intent]:
        """尝试解析用户选择"""
        message = message.strip()

        # 尝试数字选择
        if message.isdigit():
            idx = int(message) - 1
            if 0 <= idx < len(options):
                return Intent(
                    type=IntentType.CHOICE,
                    choice=options[idx].value if hasattr(options[idx], 'value') else options[idx]['value']
                )

        # 尝试直接匹配选项值
        for opt in options:
            value = opt.value if hasattr(opt, 'value') else opt['value']
            label = opt.label if hasattr(opt, 'label') else opt.get('label', '')
            if message.lower() == value.lower() or message.lower() == label.lower():
                return Intent(type=IntentType.CHOICE, choice=value)

        return None

    def _is_feedback(self, message: str) -> bool:
        """检查是否是反馈"""
        feedback_keywords = ["采纳", "接受", "adopt", "accept", "有用", "helpful", "有效"]
        return any(kw in message.lower() for kw in feedback_keywords)

    def _parse_feedback(self, message: str) -> Intent:
        """解析反馈详情"""
        message_lower = message.lower()
        adopted = any(kw in message_lower for kw in ["采纳", "接受", "adopt", "accept", "有用", "helpful"])
        return Intent(
            type=IntentType.FEEDBACK,
            adopted=adopted,
            comment=message
        )

    def _extract_path(self, message: str) -> Optional[str]:
        """提取数据路径"""
        for pattern in self.PATH_PATTERNS:
            match = re.search(pattern, message)
            if match:
                return match.group()
        return None

    def _detect_problem_type(self, message: str) -> Optional[str]:
        """检测问题类型"""
        message_lower = message.lower()
        for problem_type, keywords in self.PROBLEM_KEYWORDS.items():
            if any(kw.lower() in message_lower for kw in keywords):
                return problem_type
        return None

    def _is_continue_request(self, message: str) -> bool:
        """检查是否是继续请求"""
        continue_keywords = ["继续", "continue", "接着", "上次", "previous"]
        return any(kw in message.lower() for kw in continue_keywords)
