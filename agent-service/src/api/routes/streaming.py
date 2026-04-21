"""流式消息API"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import asyncio

from ..sse import (
    SSEStreamer,
    SSEEvent,
    SSEEventType,
    create_sse_response,
    sse_manager,
)
from ...core.agent_controller_v2 import AgentControllerV2
from ...storage import SessionStore, ConfigStore
from ...observability import get_logger, set_session_id, LogContext

logger = get_logger(__name__)
router = APIRouter(prefix="/stream", tags=["Streaming"])


class StreamMessageRequest(BaseModel):
    """流式消息请求"""
    message: str
    session_id: Optional[str] = None


class ContinueRequest(BaseModel):
    """继续请求"""
    session_id: str
    user_input: Any


# 控制器实例（实际应从依赖注入获取）
_controller: Optional[AgentControllerV2] = None


def get_controller() -> AgentControllerV2:
    """获取控制器实例"""
    global _controller
    if _controller is None:
        _controller = AgentControllerV2()
    return _controller


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
    controller = get_controller()
    streamer = SSEStreamer()

    async def event_generator():
        session_id = request.session_id

        with LogContext(session_id=session_id):
            try:
                # 处理消息
                result = await controller.process_message(
                    message=request.message,
                    session_id=session_id
                )

                # 获取会话ID
                session_id = controller.current_session.id if controller.current_session else session_id

                # 发送开始事件
                yield SSEEvent(
                    event=SSEEventType.MESSAGE_START,
                    data={"session_id": session_id}
                ).to_sse()

                # 根据结果类型发送不同事件
                if result.get("state") == "WAITING_INPUT":
                    # 需要用户输入
                    yield SSEEvent(
                        event=SSEEventType.USER_INPUT_REQUIRED,
                        data={
                            "question": result.get("response", "请选择："),
                            "options": result.get("options", []),
                            "reason": result.get("reason", ""),
                            "session_id": session_id
                        }
                    ).to_sse()

                elif result.get("state") == "COMPLETED":
                    # 分析完成，流式输出报告
                    report = result.get("report", {})

                    # 发送分析结果
                    yield SSEEvent(
                        event=SSEEventType.ANALYSIS_RESULT,
                        data={
                            "report": report,
                            "session_id": session_id
                        }
                    ).to_sse()

                    # 流式输出摘要（如果有）
                    summary = report.get("summary", "")
                    if summary:
                        # 模拟流式输出（实际可对接LLM流式API）
                        chunk_size = 20
                        for i in range(0, len(summary), chunk_size):
                            chunk = summary[i:i + chunk_size]
                            yield SSEEvent(
                                event=SSEEventType.MESSAGE_DELTA,
                                data={"content": chunk}
                            ).to_sse()
                            await asyncio.sleep(0.02)  # 模拟打字效果

                elif result.get("state") == "ERROR":
                    # 错误
                    yield SSEEvent(
                        event=SSEEventType.ERROR,
                        data={
                            "error": result.get("error", "未知错误"),
                            "session_id": session_id
                        }
                    ).to_sse()

                else:
                    # 其他状态，直接返回响应
                    response_text = result.get("response", "")
                    if response_text:
                        # 流式输出
                        chunk_size = 15
                        for i in range(0, len(response_text), chunk_size):
                            chunk = response_text[i:i + chunk_size]
                            yield SSEEvent(
                                event=SSEEventType.MESSAGE_DELTA,
                                data={"content": chunk}
                            ).to_sse()
                            await asyncio.sleep(0.02)

                # 发送结束事件
                yield SSEEvent(
                    event=SSEEventType.MESSAGE_END,
                    data={"session_id": session_id}
                ).to_sse()

            except Exception as e:
                logger.error(f"Stream message error: {e}")
                yield SSEEvent(
                    event=SSEEventType.ERROR,
                    data={"error": str(e)}
                ).to_sse()

    return create_sse_response(event_generator())


@router.post("/continue")
async def stream_continue(request: ContinueRequest):
    """
    流式继续分析

    用户选择选项后继续分析流程
    """
    controller = get_controller()
    streamer = SSEStreamer()

    async def event_generator():
        with LogContext(session_id=request.session_id):
            try:
                # 继续流程
                result = await controller.process_message(
                    message=str(request.user_input),
                    session_id=request.session_id
                )

                # 发送开始事件
                yield SSEEvent(
                    event=SSEEventType.MESSAGE_START,
                    data={"session_id": request.session_id}
                ).to_sse()

                # 处理结果（同上）
                if result.get("state") == "WAITING_INPUT":
                    yield SSEEvent(
                        event=SSEEventType.USER_INPUT_REQUIRED,
                        data={
                            "question": result.get("response", "请选择："),
                            "options": result.get("options", []),
                            "reason": result.get("reason", ""),
                            "session_id": request.session_id
                        }
                    ).to_sse()

                elif result.get("state") == "COMPLETED":
                    report = result.get("report", {})
                    yield SSEEvent(
                        event=SSEEventType.ANALYSIS_RESULT,
                        data={"report": report, "session_id": request.session_id}
                    ).to_sse()

                    summary = report.get("summary", "")
                    if summary:
                        chunk_size = 20
                        for i in range(0, len(summary), chunk_size):
                            chunk = summary[i:i + chunk_size]
                            yield SSEEvent(
                                event=SSEEventType.MESSAGE_DELTA,
                                data={"content": chunk}
                            ).to_sse()
                            await asyncio.sleep(0.02)

                elif result.get("state") == "ERROR":
                    yield SSEEvent(
                        event=SSEEventType.ERROR,
                        data={"error": result.get("error", "未知错误")}
                    ).to_sse()

                yield SSEEvent(
                    event=SSEEventType.MESSAGE_END,
                    data={"session_id": request.session_id}
                ).to_sse()

            except Exception as e:
                logger.error(f"Stream continue error: {e}")
                yield SSEEvent(
                    event=SSEEventType.ERROR,
                    data={"error": str(e)}
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
