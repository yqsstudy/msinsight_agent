"""SSE流式响应模块"""

import asyncio
import json
from typing import AsyncGenerator, Dict, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum

from fastapi import Response
from fastapi.responses import StreamingResponse

from ..observability import get_logger

logger = get_logger(__name__)


class SSEEventType(str, Enum):
    """SSE事件类型"""
    # 消息相关
    MESSAGE_START = "message_start"
    MESSAGE_DELTA = "message_delta"
    MESSAGE_END = "message_end"

    # 分析相关
    ANALYSIS_START = "analysis_start"
    ANALYSIS_STEP = "analysis_step"
    ANALYSIS_RESULT = "analysis_result"
    ANALYSIS_END = "analysis_end"

    # 用户交互
    USER_INPUT_REQUIRED = "user_input_required"

    # 错误
    ERROR = "error"

    # 心跳
    HEARTBEAT = "heartbeat"


@dataclass
class SSEEvent:
    """SSE事件"""
    event: str
    data: Dict[str, Any]
    id: Optional[str] = None
    retry: Optional[int] = None

    def to_sse(self) -> str:
        """转换为SSE格式"""
        lines = []
        if self.id:
            lines.append(f"id: {self.id}")
        if self.event:
            lines.append(f"event: {self.event}")
        if self.retry:
            lines.append(f"retry: {self.retry}")
        lines.append(f"data: {json.dumps(self.data, ensure_ascii=False)}")
        return "\n".join(lines) + "\n\n"


class SSEStreamer:
    """SSE流式输出器"""

    def __init__(self):
        self._message_id = 0

    def _next_id(self) -> str:
        self._message_id += 1
        return str(self._message_id)

    async def stream_message(
        self,
        content_generator: AsyncGenerator[str, None],
        session_id: str = None
    ) -> AsyncGenerator[str, None]:
        """
        流式输出消息

        Args:
            content_generator: 内容生成器
            session_id: 会话ID
        """
        # 发送开始事件
        yield SSEEvent(
            event=SSEEventType.MESSAGE_START,
            data={"session_id": session_id},
            id=self._next_id()
        ).to_sse()

        # 流式输出内容
        async for chunk in content_generator:
            yield SSEEvent(
                event=SSEEventType.MESSAGE_DELTA,
                data={"content": chunk},
                id=self._next_id()
            ).to_sse()

        # 发送结束事件
        yield SSEEvent(
            event=SSEEventType.MESSAGE_END,
            data={},
            id=self._next_id()
        ).to_sse()

    async def stream_analysis(
        self,
        flow_name: str,
        step_generator: AsyncGenerator[Dict[str, Any], None],
        session_id: str = None
    ) -> AsyncGenerator[str, None]:
        """
        流式输出分析过程

        Args:
            flow_name: 流程名称
            step_generator: 步骤生成器
            session_id: 会话ID
        """
        # 发送分析开始
        yield SSEEvent(
            event=SSEEventType.ANALYSIS_START,
            data={"flow_name": flow_name, "session_id": session_id},
            id=self._next_id()
        ).to_sse()

        # 流式输出步骤
        async for step_data in step_generator:
            event_type = step_data.get("event", SSEEventType.ANALYSIS_STEP)

            if step_data.get("waiting_input"):
                # 需要用户输入
                yield SSEEvent(
                    event=SSEEventType.USER_INPUT_REQUIRED,
                    data=step_data,
                    id=self._next_id()
                ).to_sse()
            elif step_data.get("error"):
                yield SSEEvent(
                    event=SSEEventType.ERROR,
                    data=step_data,
                    id=self._next_id()
                ).to_sse()
            else:
                yield SSEEvent(
                    event=event_type,
                    data=step_data,
                    id=self._next_id()
                ).to_sse()

        # 发送分析结束
        yield SSEEvent(
            event=SSEEventType.ANALYSIS_END,
            data={"session_id": session_id},
            id=self._next_id()
        ).to_sse()

    async def send_heartbeat(self) -> str:
        """发送心跳"""
        return SSEEvent(
            event=SSEEventType.HEARTBEAT,
            data={"timestamp": asyncio.get_event_loop().time()},
            id=self._next_id()
        ).to_sse()


def create_sse_response(
    generator: AsyncGenerator[str, None]
) -> StreamingResponse:
    """创建SSE响应"""
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用nginx缓冲
        }
    )


class SSEConnectionManager:
    """SSE连接管理器"""

    def __init__(self):
        self._active_connections: Dict[str, asyncio.Queue] = {}

    async def connect(self, session_id: str) -> asyncio.Queue:
        """建立连接"""
        queue = asyncio.Queue()
        self._active_connections[session_id] = queue
        logger.info(f"SSE connection established: session_id=session_id")
        return queue

    async def disconnect(self, session_id: str):
        """断开连接"""
        if session_id in self._active_connections:
            del self._active_connections[session_id]
            logger.info(f"SSE connection closed: session_id=session_id")

    async def send_event(self, session_id: str, event: SSEEvent):
        """发送事件"""
        if session_id in self._active_connections:
            await self._active_connections[session_id].put(event)

    async def broadcast(self, event: SSEEvent):
        """广播事件"""
        for queue in self._active_connections.values():
            await queue.put(event)

    def get_active_count(self) -> int:
        """获取活跃连接数"""
        return len(self._active_connections)


# 全局SSE管理器
sse_manager = SSEConnectionManager()
