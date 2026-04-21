"""消息处理API - 完整实现"""

from datetime import datetime
from typing import Optional, List
import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...core import AgentController
from ...models import Session

router = APIRouter(prefix="/api/sessions", tags=["messages"])


class MessageRequest(BaseModel):
    content: str


class MessageResponse(BaseModel):
    response: str
    state: str
    report: Optional[dict] = None
    options: Optional[List[dict]] = None
    question: Optional[str] = None
    reason: Optional[str] = None


# 全局Agent控制器实例
_agent_controller: Optional[AgentController] = None


def get_agent_controller() -> AgentController:
    """获取Agent控制器实例"""
    global _agent_controller
    if _agent_controller is None:
        _agent_controller = AgentController()
    return _agent_controller


@router.post("/{session_id}/messages", response_model=MessageResponse)
async def send_message(session_id: str, request: MessageRequest):
    """发送消息到会话"""
    controller = get_agent_controller()

    # 处理消息
    result = await controller.process_message(
        message=request.content,
        session_id=session_id
    )

    return MessageResponse(
        response=result.get("response", ""),
        state=result.get("state", "IDLE"),
        report=result.get("report"),
        options=result.get("options"),
        question=result.get("question"),
        reason=result.get("reason")
    )


@router.post("", response_model=MessageResponse)
async def create_and_send_message(request: MessageRequest):
    """创建新会话并发送消息"""
    controller = get_agent_controller()

    # 创建新会话并处理消息
    session = controller.create_session()

    result = await controller.process_message(
        message=request.content,
        session_id=session.id
    )

    return MessageResponse(
        response=result.get("response", ""),
        state=result.get("state", "IDLE"),
        report=result.get("report"),
        options=result.get("options"),
        question=result.get("question"),
        reason=result.get("reason")
    )
