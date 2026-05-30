"""Harness report and feedback API."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...storage import ConfigStore, SessionStore

router = APIRouter(prefix="/api/reports", tags=["reports"])

_session_store: Optional[SessionStore] = None


class ReportFeedbackRequest(BaseModel):
    session_id: str
    adopted: Optional[bool] = None
    comment: Optional[str] = None


def get_session_store() -> SessionStore:
    global _session_store
    if _session_store is None:
        config = ConfigStore()
        _session_store = SessionStore(config.get_storage_config().sqlite_path)
    return _session_store


@router.get("/sessions/{session_id}")
async def list_session_reports(session_id: str):
    store = get_session_store()
    return {"reports": store.list_reports(session_id)}


@router.get("/{report_id}")
async def get_report(report_id: str):
    store = get_session_store()
    report = store.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"report": report}


@router.post("/{report_id}/feedback")
async def submit_report_feedback(report_id: str, request: ReportFeedbackRequest):
    store = get_session_store()
    report = store.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report["session_id"] != request.session_id:
        raise HTTPException(status_code=400, detail="Report does not belong to session")
    feedback = store.save_feedback(
        session_id=request.session_id,
        report_id=report_id,
        adopted=request.adopted,
        comment=request.comment,
    )
    return {"success": True, "feedback": feedback}
