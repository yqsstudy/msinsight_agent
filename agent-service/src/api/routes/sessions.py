"""会话管理API"""

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException

from ...models import Session
from ...storage import SessionStore

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# 全局会话存储实例
_session_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    """获取会话存储实例"""
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store


@router.post("")
async def create_session(user_id: str = "default"):
    """创建新会话"""
    store = get_session_store()
    import uuid
    session = Session(
        id=str(uuid.uuid4()),
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    store.save(session)
    return {
        "session_id": session.id,
        "created_at": session.created_at.isoformat()
    }


@router.get("/{session_id}")
async def get_session(session_id: str):
    """获取会话详情"""
    store = get_session_store()
    session = store.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": session.to_dict()}


@router.get("")
async def list_sessions(user_id: str = "default", limit: int = 20):
    """获取会话列表"""
    store = get_session_store()
    sessions = store.list_all(limit)
    return {
        "sessions": [
            {
                "id": s.id,
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
                "state": s.state,
                "message_count": len(s.messages)
            }
            for s in sessions
        ]
    }


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    store = get_session_store()
    success = store.delete(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True}
