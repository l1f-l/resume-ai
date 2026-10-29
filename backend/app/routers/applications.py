"""投递路由：生成求职信 → 附 PDF → 发到注册邮箱 → 落库 → 看板流转。"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from urllib.parse import quote

from .. import mailer
from ..applications import STATUS_LABELS, ApplicationError, application_store
from ..config import settings
from ..deps import get_session
from ..jobs import job_store
from ..matches import match_store
from ..runtime import llm
from ..schemas import ApplicationOut
from ..security import get_current_user
from ..services import cover, exporter
from ..services.state import Stage
from ..session import store

log = logging.getLogger("applications.api")
router = APIRouter(prefix="/applications", tags=["applications"])


class ApplyIn(BaseModel):
    session_id: str = Field(min_length=4, max_length=40)
    job_id: str = Field(min_length=3, max_length=40)
    note: str = Field(default="", max_length=200)


class StatusIn(BaseModel):
    status: str = Field(min_length=3, max_length=20)
    note: str = Field(default="", max_length=200)


def _out(row: dict) -> dict:
    return ApplicationOut(
        id=row["id"],
        job_id=row["job_id"],
        job_title=row.get("job_title") or "",
        company=row.get("company") or "",
        city=row.get("city") or "",
        salary=row.get("salary") or "",
        status=row["status"],
        match_score=int(row.get("match_score") or 0),
        email_to=row.get("email_to") or "",
        email_subject=row.get("email_subject") or "",
        mail_status=row.get("mail_status") or "pending",
        mail_error=row.get("mail_error") or "",
        attachment=row.get("attachment") or "",
        note=row.get("note") or "",
        created_at=float(row.get("created_at") or 0),
        updated_at=float(row.get("updated_at") or 0),
    ).model_dump() | {"status_label": STATUS_LABELS.get(row["status"], row["status"])}


@router.post("")
async def apply(body: ApplyIn, user: dict = Depends(get_current_user)) -> dict:
    session = get_session(body.session_id, user)
    if session.stage not in (Stage.OPTIMIZED, Stage.REVIEWED):
        raise HTTPException(
            status_code=409, detail="请先完成简历优化（STAR 重写），再投递岗位"
        )
    job = job_store.get(body.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")
    if application_store.exists(user["id"], job["id"]):
        raise HTTPException(status_code=409, detail="该岗位已投递过，请到投递看板查看进度")

    app_id = uuid.uuid4().hex[:12]
    subject, body_html, note = await cover.compose(session.resume, job, llm)

    name = session.resume.basics.name or "resume"
    pdf_name = exporter.safe_filename(f"{name}-{job['title']}", "pdf")
    pdf = exporter.render_pdf(session.resume, "optimized")
    attachment = mailer.save_attachment(pdf, pdf_name, app_id)

    # 收件人固定为当前登录账号的注册邮箱，前端无法指定，避免被当成群发工具
    result = await mailer.send_mail(
        to=user["email"],
        subject=subject,
        html=body_html,
        pdf=pdf,
        pdf_name=pdf_name,
        tag=app_id,
        attachment=attachment,
    )

    row = application_store.create(
        user_id=user["id"],
        session_id=session.id,
        job_id=job["id"],
        match_score=match_store.session_scores(session.id).get(job["id"], 0),
        email_to=user["email"],
        email_subject=subject,
        email_body=body_html,
        mail_status=result.status,
        mail_error=result.error,
        attachment=attachment,
        note=body.note,
    )
    return {
        "application": _out(row),
        "mail": {
            "status": result.status,
            "to": result.to,
            "subject": result.subject,
            "error": result.error,
            "preview": body_html,
            "smtp_ready": settings.smtp_ready,
        },
        "note": note,
    }


@router.get("")
async def list_applications(
    user: dict = Depends(get_current_user), status: str = ""
) -> dict:
    rows = application_store.list(user["id"], status or None)
    return {
        "items": [_out(r) for r in rows],
        "summary": application_store.summary(user["id"]),
        "smtp_ready": settings.smtp_ready,
    }


@router.get("/summary")
async def summary(user: dict = Depends(get_current_user)) -> dict:
    return application_store.summary(user["id"])


@router.get("/{app_id}/events")
async def events(app_id: str, user: dict = Depends(get_current_user)) -> dict:
    return {"items": application_store.events(app_id, user["id"])}


@router.patch("/{app_id}")
async def update_status(
    app_id: str, body: StatusIn, user: dict = Depends(get_current_user)
) -> dict:
    try:
        row = application_store.update_status(app_id, user["id"], body.status, body.note)
    except ApplicationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"application": _out(row)}


@router.get("/{app_id}/resume")
async def download_resume(app_id: str, user: dict = Depends(get_current_user)) -> Response:
    """下载投递时使用的 PDF（留档版本，不是当前简历）。"""
    row = application_store.get(app_id, user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="投递记录不存在")
    rel = row.get("attachment") or ""
    if not rel:
        raise HTTPException(status_code=404, detail="该投递未保存附件")
    path = (settings.data_dir.parent / rel).resolve()
    outbox = (settings.data_dir / "outbox").resolve()
    if outbox not in path.parents or not path.exists():  # 防目录穿越
        raise HTTPException(status_code=404, detail="附件不存在")
    data = path.read_bytes()
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(path.name)}",
            "Content-Length": str(len(data)),
        },
    )
