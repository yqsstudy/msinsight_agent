"""WebSocket支持 - 用于流式响应"""

from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect
import json

from ..core import DialogManager
from ..storage import SessionStore


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.active_connections: dict = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket

    def disconnect(self, session_id: str):
        self.active_connections.pop(session_id, None)

    async def send_message(self, session_id: str, message: dict):
        if session_id in self.active_connections:
            await self.active_connections[session_id].send_json(message)

    async def broadcast(self, message: dict):
        for connection in self.active_connections.values():
            await connection.send_json(message)


manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket端点"""
    await manager.connect(websocket, session_id)

    dialog_manager = DialogManager(SessionStore())

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            msg_type = message.get("type")

            if msg_type == "user_message":
                # 处理用户消息
                content = message.get("content", "")

                # 发送进度更新
                await manager.send_message(session_id, {
                    "type": "progress",
                    "step": "processing",
                    "message": "正在处理您的请求..."
                })

                # TODO: 实际处理逻辑
                response = f"收到消息: {content}"

                # 发送响应
                await manager.send_message(session_id, {
                    "type": "response",
                    "content": response
                })

            elif msg_type == "user_choice":
                # 处理用户选择
                choice = message.get("choice")

                await manager.send_message(session_id, {
                    "type": "progress",
                    "step": "analyzing",
                    "message": f"已选择: {choice}，继续分析..."
                })

                # TODO: 继续分析流程

    except WebSocketDisconnect:
        manager.disconnect(session_id)
    except Exception as e:
        await manager.send_message(session_id, {
            "type": "error",
            "message": str(e)
        })
        manager.disconnect(session_id)
