"""WebSocket支持 - 用于流式响应"""

from fastapi import WebSocket, status

from ..observability import get_logger

logger = get_logger(__name__)


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
    """WebSocket endpoint is disabled until it shares the SSE orchestrator state machine."""
    logger.warning(f"Rejected unsupported WebSocket connection: session_id={session_id}")
    await websocket.close(
        code=status.WS_1003_UNSUPPORTED_DATA,
        reason="WebSocket transport is not supported; use /api/stream/message SSE endpoints.",
    )
