"""流式消息API"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Any
import asyncio

from ..sse import (
    SSEEvent,
    SSEEventType,
    create_sse_response,
    sse_manager,
)
from ...core.orchestrator import Orchestrator
from ...models.orchestration import SSEEventEnvelope
from ...observability import get_logger, LogContext

logger = get_logger(__name__)
router = APIRouter(prefix="/api/stream", tags=["Streaming"])


class StreamMessageRequest(BaseModel):
    """流式消息请求"""
    message: str
    session_id: Optional[str] = None


class ContinueRequest(BaseModel):
    """继续请求"""
    session_id: str
    user_input: Any


_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    """获取 Orchestrator 实例"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


async def close_orchestrator() -> None:
    """关闭全局 Orchestrator 持有的外部资源。"""
    global _orchestrator
    if _orchestrator is not None:
        await _orchestrator.close()
        _orchestrator = None


def envelope_to_sse(envelope: SSEEventEnvelope) -> str:
    payload = envelope.model_dump(mode="json")
    data = payload.get("data") or {}
    data["session_id"] = payload.get("session_id")
    return SSEEvent(
        event=payload["event"],
        data=data,
        id=payload.get("event_id"),
    ).to_sse()


@router.post("/message")
async def stream_message(request: StreamMessageRequest):
    """
    流式发送消息

    返回SSE流，事件类型：
    - message_start: 消息开始
    - message_delta: 消息片段
    - analysis_step: 分析步骤
    - user_input_required: 需要用户输入
    - message_end: 消息结束
    - error: 错误
    """
    orchestrator = get_orchestrator()

    async def event_generator():
        with LogContext(session_id=request.session_id):
            try:
                async for envelope in orchestrator.handle_message(request.session_id, request.message):
                    yield envelope_to_sse(envelope)
            except Exception as e:
                logger.error(f"Stream message error: {e}")
                yield SSEEvent(
                    event=SSEEventType.ERROR,
                    data={"error": str(e), "session_id": request.session_id}
                ).to_sse()

    return create_sse_response(event_generator())


@router.post("/continue")
async def stream_continue(request: ContinueRequest):
    """
    流式继续分析

    用户选择选项后继续分析流程
    """
    orchestrator = get_orchestrator()

    async def event_generator():
        with LogContext(session_id=request.session_id):
            try:
                async for envelope in orchestrator.continue_with_input(request.session_id, request.user_input):
                    yield envelope_to_sse(envelope)
            except Exception as e:
                logger.error(f"Stream continue error: {e}")
                yield SSEEvent(
                    event=SSEEventType.ERROR,
                    data={"error": str(e), "session_id": request.session_id}
                ).to_sse()

    return create_sse_response(event_generator())


@router.get("/connect/{session_id}")
async def sse_connect(session_id: str):
    """
    SSE连接端点

    用于建立长连接，接收实时事件
    """
    queue = await sse_manager.connect(session_id)

    async def event_generator():
        try:
            # 发送连接成功
            yield SSEEvent(
                event="connected",
                data={"session_id": session_id}
            ).to_sse()

            # 持续监听队列
            while True:
                try:
                    # 等待事件，带超时
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield event.to_sse()
                except asyncio.TimeoutError:
                    # 发送心跳
                    yield SSEEvent(
                        event=SSEEventType.HEARTBEAT,
                        data={}
                    ).to_sse()

        except asyncio.CancelledError:
            pass
        finally:
            await sse_manager.disconnect(session_id)

    return create_sse_response(event_generator())
