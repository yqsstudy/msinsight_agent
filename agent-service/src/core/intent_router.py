"""Intent routing for Agent Harness."""

import re
from typing import Optional

from ..models.orchestration import IntentDecision, IntentType
from ..storage import SessionStore

PATH_PATTERN = re.compile(r"([A-Za-z]:[/\\][^\s，,]+|/[^\s，,]+)")


class IntentRouter:
    """Rule-based intent router with conservative defaults."""

    def __init__(self, session_store: Optional[SessionStore] = None):
        self.session_store = session_store

    def route(self, message: str, session_id: Optional[str] = None) -> IntentDecision:
        text = message.strip()
        lowered = text.lower()
        extracted = {}

        path_match = PATH_PATTERN.search(text)
        if path_match:
            extracted["path"] = path_match.group(1)

        if session_id and self.session_store and self.session_store.get_active_pending_input(session_id):
            return IntentDecision(
                intent=IntentType.CONTINUE_ANALYSIS,
                confidence=0.95,
                reason="当前会话存在待用户输入项",
                extracted=extracted,
            )

        if any(keyword in text for keyword in ["你好", "您好", "你能做什么", "你是谁", "hello", "hi"]):
            return IntentDecision(
                intent=IntentType.CHAT,
                confidence=0.95,
                reason="用户进行普通聊天或询问系统能力",
                extracted=extracted,
            )

        if any(keyword in text for keyword in ["报告", "总结", "复盘"]):
            return IntentDecision(
                intent=IntentType.REPORT_GENERATION,
                confidence=0.85,
                reason="用户要求生成或查看总结报告",
                extracted=extracted,
            )

        if extracted.get("path") and any(keyword in text for keyword in ["分析", "定位", "诊断", "慢", "性能"]):
            return IntentDecision(
                intent=IntentType.PROFILING_ANALYSIS,
                confidence=0.9,
                reason="用户提供了本地路径并要求进行性能分析",
                extracted=extracted,
            )

        if any(keyword in text for keyword in ["分析", "定位", "为什么慢", "性能问题", "通信慢", "快慢卡", "瓶颈", "profiling"]):
            return IntentDecision(
                intent=IntentType.DIAGNOSIS,
                confidence=0.82,
                reason="用户描述了性能诊断目标",
                extracted=extracted,
            )

        if any(keyword in text for keyword in ["查找", "检索", "资料", "文档"]):
            return IntentDecision(
                intent=IntentType.KNOWLEDGE_RETRIEVE,
                confidence=0.78,
                reason="用户要求检索知识资料",
                extracted=extracted,
            )

        if any(keyword in text for keyword in ["怎么", "如何", "是什么", "什么意思", "用法", "参数"]):
            return IntentDecision(
                intent=IntentType.KNOWLEDGE_QA,
                confidence=0.75,
                reason="用户提出知识问答或工具用法问题",
                extracted=extracted,
            )

        return IntentDecision(
            intent=IntentType.CLARIFICATION,
            confidence=0.5,
            reason="无法确定是否需要知识问答或 profiling 诊断",
            extracted=extracted,
        )
