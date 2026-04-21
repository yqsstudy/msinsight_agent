"""反馈API"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...case_lib import CaseLibManager

router = APIRouter(prefix="/api/cases", tags=["feedback"])

# 全局案例管理器实例
_case_manager: Optional[CaseLibManager] = None


def get_case_manager() -> CaseLibManager:
    global _case_manager
    if _case_manager is None:
        _case_manager = CaseLibManager()
    return _case_manager


class FeedbackRequest(BaseModel):
    adopted: bool
    comment: Optional[str] = None


@router.post("/{case_id}/feedback")
async def submit_feedback(case_id: str, request: FeedbackRequest):
    """提交案例反馈"""
    manager = get_case_manager()

    case = manager.load_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    manager.update_feedback(case_id, request.adopted, request.comment)

    return {"success": True}


@router.get("")
async def list_cases(limit: int = 50):
    """列出案例"""
    manager = get_case_manager()
    cases = manager.list_cases(limit)
    return {
        "cases": [c.to_dict() for c in cases]
    }


@router.get("/{case_id}")
async def get_case(case_id: str):
    """获取案例详情"""
    manager = get_case_manager()
    case = manager.load_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return {"case": case.to_dict()}


@router.delete("/{case_id}")
async def delete_case(case_id: str):
    """删除案例"""
    manager = get_case_manager()
    success = manager.delete_case(case_id)
    if not success:
        raise HTTPException(status_code=404, detail="Case not found")
    return {"success": True}
