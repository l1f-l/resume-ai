"""HTTP 路由 + SSE 协议。"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .config import settings
from .deps import get_session
from .jobs import job_store
from .runtime import llm
from .schemas import AnswerFeedback, InterviewReport, ResumeDoc
from .security import get_current_user
from .services import exporter
from .services.agents import InterviewerAgent, ResumeAgent
from .services.pdf_parser import PDFParseError, parse_pdf, structure_resume
from .services.rag import store as template_store
from .services.state import IllegalTransition, Stage
from .session import Session, apply_rewrite, reset_interview, store
from .sse import sse, sse_stream
from .routers import applications as applications_router
from .routers import auth as auth_router
from .routers import jobs as jobs_router
from .routers import matching as matching_router

log = logging.getLogger("api")
router = APIRouter(prefix="/api")
router.include_router(auth_router.router)
router.include_router(jobs_router.router)
router.include_router(matching_router.router)
router.include_router(applications_router.router)


# --------------------------------------------------------------------------- #
# SSE 基础（实现见 sse.py，此处保留 re-export 供测试与旧代码引用）
# --------------------------------------------------------------------------- #


def require_stage(session: Session, *allowed: str) -> None:
    """非法阶段直接 409，而不是抛 500。"""
    if session.stage not in allowed:
        labels = "、".join(Stage.LABELS.get(a, a) for a in allowed)
        raise HTTPException(
            status_code=409,
            detail=f"当前阶段为「{Stage.LABELS.get(session.stage, session.stage)}」，"
                   f"该操作只允许在「{labels}」执行",
        )


# --------------------------------------------------------------------------- #
# 请求体
# --------------------------------------------------------------------------- #
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


# --------------------------------------------------------------------------- #
# 元信息
# --------------------------------------------------------------------------- #
@router.get("/health")
async def health() -> dict:
    size = template_store.size()  # 触发懒加载，顺带返回模板数量
    from .services.ocr import available_engines  # noqa: PLC0415

    return {
        "status": "ok",
        "llm_mode": "mock" if llm.is_mock else "deepseek",
        "llm_label": settings.llm_label if not llm.degraded else "内置演示引擎（已降级）",
        "model": settings.deepseek_model,
        "llm": {
            "mode": llm.mode,
            "degraded": llm.degraded,
            "reason": llm.degrade_reason,
            "last_error": llm.last_error,
            "has_key": bool(settings.deepseek_api_key),
        },
        "ocr": {
            "enabled": settings.ocr_enabled,
            "engines": available_engines(),
            "min_chars": settings.ocr_min_chars,
        },
        "db": {"path": str(settings.db_path), "sessions": store.db.count()},
        "rag": {"backend": template_store.backend, "templates": size},
        "jobs": {"total": job_store.count(), "index": job_store.backend},
        "auth": {"mode": "jwt", "cookie": settings.jwt_cookie, "header": settings.token_header},
        "mail": {"smtp_ready": settings.smtp_ready, "host": settings.smtp_host or ""},
        "stages": [Stage.LABELS[s] for s in Stage.ALL],
    }


@router.post("/llm/reset")
async def reset_llm() -> dict:
    """熔断后手动恢复：清空降级标记，下一次请求重新尝试真实模型。"""
    llm.reset()
    return {"ok": True, "mode": llm.mode, "is_mock": llm.is_mock}


@router.get("/sessions")
async def list_sessions(user: dict = Depends(get_current_user), limit: int = 20) -> dict:
    return {"items": store.list_recent(limit, user_id=user["id"])}


@router.get("/templates")
async def list_templates(k: int = 6, q: str = "") -> dict:
    hits = template_store.search(q or "优秀简历 STAR 量化", k=k)
    return {"backend": template_store.backend, "items": [h.model_dump() for h in hits]}


# --------------------------------------------------------------------------- #
# 上传 + 解析
# --------------------------------------------------------------------------- #
@router.post("/sessions")
async def create_session(
    user: dict = Depends(get_current_user),
    file: UploadFile | None = File(default=None),
    jd: str = Form(default=""),
    job_id: str = Form(default=""),
) -> JSONResponse:
    if file is None:
        raise HTTPException(status_code=400, detail="请上传 PDF 简历")
    filename = file.filename or "resume.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 格式（.pdf）")
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"文件超过 {settings.max_upload_mb}MB 限制")
    if not jd.strip() and not job_id:
        raise HTTPException(status_code=400, detail="请填写目标岗位 JD，或从岗位池选择一个岗位")

    if job_id:
        from .jobs import job_store  # noqa: PLC0415

        job = job_store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="所选岗位不存在")
        # 显式选了岗位池岗位时，以岗位 JD 为准（手填 JD 只用于「自由诊断」模式）
        jd = job["jd_text"]

    try:
        parsed = parse_pdf(data)
    except PDFParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    resume, struct_mode = await structure_resume(parsed.text[: settings.max_resume_chars], llm)
    session = store.create(
        user_id=user["id"],
        job_id=job_id,
        file_name=filename,
        pages=parsed.pages,
        chars=parsed.chars,
        resume_text=parsed.text,
        jd=jd.strip(),
        resume=resume,
        llm_mode="mock" if llm.is_mock else settings.deepseek_model,
        parse_meta={
            "method": parsed.method,
            "structure": struct_mode,
            "scanned": parsed.scanned,
            "ocr_engine": parsed.ocr_engine,
            "ocr_renderer": parsed.ocr_renderer,
            "warnings": parsed.warnings,
        },
    )
    session.advance(Stage.PARSED)
    source = (
        f"（扫描件，已用 {parsed.ocr_engine} OCR 识别）" if parsed.scanned else ""
    )
    session.add_message(
        "assistant",
        f"已解析《{filename}》{source}，共 {parsed.pages} 页、{parsed.chars} 字，"
        f"识别出 {len(resume.experiences)} 段工作经历、{len(resume.projects)} 个项目。"
        "接下来我会对照 JD 做匹配度诊断。",
    )
    return JSONResponse(
        {
            "session_id": session.id,
            "stage": session.stage,
            "file_name": filename,
            "pages": parsed.pages,
            "chars": parsed.chars,
            "parse": session.parse_meta,
            "resume": resume.model_dump(),
            "message": session.messages[0].content if session.messages else "",
        }
    )


@router.get("/sessions/{sid}")
async def read_session(sid: str, user: dict = Depends(get_current_user)) -> dict:
    return get_session(sid, user).summary().model_dump()


@router.delete("/sessions/{sid}")
async def delete_session(sid: str, user: dict = Depends(get_current_user)) -> dict:
    get_session(sid, user)
    store.drop(sid)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# 诊断
# --------------------------------------------------------------------------- #
@router.post("/sessions/{sid}/analyze")
async def analyze(sid: str, user: dict = Depends(get_current_user)) -> StreamingResponse:
    session = get_session(sid, user)
    require_stage(session, Stage.PARSED)

    async def gen() -> AsyncIterator[tuple[str, dict]]:
        agent = ResumeAgent(llm)
        holds: list[str] = []
        async for event, data in agent.diagnose(session.resume, session.jd, session.resume_text):
            if event == "token":
                holds.append(data.get("text", ""))
            if event == "diagnosis":
                from .schemas import Diagnosis

                session.diagnosis = Diagnosis.model_validate(data)
            if event == "state":
                session.advance(data["stage"])
            if event == "phase":
                yield event, data
                continue
            if event == "diagnosis":
                yield event, {**data, "session_id": sid}
                continue
            yield event, data
        if holds:
            session.add_message("assistant", "".join(holds))
        yield "session", session.summary().model_dump()

    return sse_stream(gen(), session)


# --------------------------------------------------------------------------- #
# 聊天：追问 -> 重写
# --------------------------------------------------------------------------- #
@router.post("/sessions/{sid}/chat")
async def chat(sid: str, body: ChatIn, user: dict = Depends(get_current_user)) -> StreamingResponse:
    session = get_session(sid, user)
    if session.stage in (Stage.NEW, Stage.PARSED):
        raise HTTPException(status_code=409, detail="请先完成简历诊断，再进入追问环节")
    message = body.message.strip()
    if session.stage == Stage.INTERVIEWING:
        # 面试中的输入就是「作答」，复用同一套评分流程，前端只需要一个输入框
        question = session.current_question()
        if question is None:
            raise HTTPException(status_code=409, detail="题目已全部作答，请查看复盘报告")
        session.add_message("user", message)
        return sse_stream(_answer_flow(session, question, message), session)

    session.add_message("user", message)

    async def revise_flow() -> AsyncIterator[tuple[str, dict]]:
        agent = ResumeAgent(llm)
        holds: list[str] = []
        async for event, data in agent.revise(session.resume, message):
            if event == "token":
                holds.append(data.get("text", ""))
            if event == "rewrite":
                apply_rewrite(session, data)
                yield "resume", {"resume": session.resume.model_dump()}
            yield event, data
        if holds:
            session.add_message("assistant", "".join(holds))
        yield "session", session.summary().model_dump()

    async def clarify_flow() -> AsyncIterator[tuple[str, dict]]:
        agent = ResumeAgent(llm)
        holds: list[str] = []

        gap = session.current_gap()
        skipped = message in {"跳过", "skip", "不知道", "没有数据"}
        if gap:
            session.mark_answered("" if skipped else message)
            ACKS = ("收到，这个数据很有用。", "好，这条我记下了。", "有数了，我会把它写进结果里。")
            ack = ("没关系，这条先留白，我用现有信息改写。" if skipped
                   else ACKS[len(session.qa_pairs) % len(ACKS)])
            yield "token", {"text": ack}
            holds.append(ack)

        if session.stage == Stage.DIAGNOSED:
            session.advance(Stage.CLARIFYING)

        # 还有追问 → 继续问
        nxt = session.current_gap()
        if nxt:
            bullet_text = _bullet_text(session.resume, nxt.bullet_id)
            async for event, data in agent.ask(session.resume, nxt, bullet_text):
                if event == "token":
                    holds.append(data.get("text", ""))
                yield event, data
            yield "gaps", {
                "gaps": [g.model_dump() for g in session.diagnosis.gap_questions],
                "answered": session.gap_progress()[0],
                "total": session.gap_progress()[1],
            }
            session.advance(Stage.CLARIFYING)
            if holds:
                session.add_message("assistant", "".join(holds))
            yield "session", session.summary().model_dump()
            return

        # 追问结束 → 重写
        session.advance(Stage.READY_TO_REWRITE)
        yield "state", {"stage": session.stage, "label": Stage.LABELS[session.stage]}
        answers_map = {q: a for q, a in session.qa_pairs}
        async for event, data in agent.rewrite(
            session.resume, session.answers, session.jd, answers_map
        ):
            if event == "token":
                holds.append(data.get("text", ""))
            if event == "rewrite":
                apply_rewrite(session, data)
                yield "rewrite", data
                yield "resume", {"resume": session.resume.model_dump()}
                continue
            if event == "state":
                if session.stage == Stage.READY_TO_REWRITE:
                    session.advance(Stage.OPTIMIZED)
                yield "state", {"stage": session.stage, "label": Stage.LABELS[session.stage]}
                continue
            yield event, data
        if holds:
            session.add_message("assistant", "".join(holds))
        yield "session", session.summary().model_dump()

    if session.stage in (Stage.OPTIMIZED, Stage.REVIEWED):
        return sse_stream(revise_flow(), session)
    return sse_stream(clarify_flow(), session)


def _bullet_text(resume: ResumeDoc, bullet_id: str) -> str:
    for b in resume.all_bullets():
        if b.id == bullet_id:
            return b.optimized or b.original
    return ""


# --------------------------------------------------------------------------- #
# 模拟面试
# --------------------------------------------------------------------------- #
@router.post("/sessions/{sid}/interview/start")
async def interview_start(sid: str, user: dict = Depends(get_current_user)) -> StreamingResponse:
    session = get_session(sid, user)
    if session.stage not in (Stage.OPTIMIZED, Stage.REVIEWED):
        raise HTTPException(status_code=409, detail="请先完成简历优化，再进入模拟面试")
    reset_interview(session)

    async def gen() -> AsyncIterator[tuple[str, dict]]:
        agent = InterviewerAgent(llm)
        holds: list[str] = []
        try:
            hits = template_store.search(session.jd, k=2)
        except Exception:  # noqa: BLE001
            hits = []
        async for event, data in agent.make_questions(session.resume, session.jd, hits):
            if event == "questions":
                from .schemas import InterviewQuestion

                session.questions = [InterviewQuestion.model_validate(q) for q in data["questions"]]
                session.cursor = 0
            if event == "token":
                holds.append(data.get("text", ""))
            if event == "state" and session.stage == Stage.OPTIMIZED:
                session.advance(data["stage"])
            yield event, data
        if holds:
            session.add_message("assistant", "".join(holds))
        yield "session", session.summary().model_dump()

    return sse_stream(gen(), session)


async def _answer_flow(session: Session, question, answer: str) -> AsyncIterator[tuple[str, dict]]:
    """单题评分 → 下一题 / 复盘。chat 与 interview/answer 共用。"""
    agent = InterviewerAgent(llm)
    holds: list[str] = []
    async for event, data in agent.evaluate(question, answer):
        if event == "token":
            holds.append(data.get("text", ""))
        if event == "feedback":
            session.feedbacks.append(AnswerFeedback.model_validate(data))
            session.cursor += 1
            yield "feedback", data
            continue
        yield event, data

    if session.cursor >= len(session.questions):
        async for event, data in agent.wrap_up(session.feedbacks, session.questions):
            if event == "token":
                holds.append(data.get("text", ""))
            if event == "report":
                session.report = InterviewReport.model_validate(data)
            if event == "state":
                if session.stage == Stage.INTERVIEWING:
                    session.advance(Stage.REVIEWED)
                yield "state", {"stage": session.stage, "label": Stage.LABELS[session.stage]}
                continue
            yield event, data
    else:
        nq = session.questions[session.cursor]
        async for event, data in agent.ask_question(nq, session.cursor + 1):
            if event == "token":
                holds.append(data.get("text", ""))
            yield event, data

    if holds:
        session.add_message("assistant", "".join(holds))
    yield "session", session.summary().model_dump()


@router.post("/sessions/{sid}/interview/answer")
async def interview_answer(
    sid: str, body: AnswerIn, user: dict = Depends(get_current_user)
) -> StreamingResponse:
    session = get_session(sid, user)
    require_stage(session, Stage.INTERVIEWING)
    question = session.current_question()
    if question is None:
        raise HTTPException(status_code=409, detail="题目已全部作答，请查看复盘报告")
    answer = body.answer.strip()
    session.add_message("user", answer)
    return sse_stream(_answer_flow(session, question, answer), session)


# --------------------------------------------------------------------------- #
# 导出
# --------------------------------------------------------------------------- #
@router.get("/sessions/{sid}/export")
async def export(
    sid: str,
    user: dict = Depends(get_current_user),
    format: str = "html",
    variant: str = "optimized",
) -> Response:
    session = get_session(sid, user)
    if variant not in {"optimized", "diff", "original"}:
        raise HTTPException(status_code=400, detail="variant 仅支持 optimized | diff | original")
    if not session.resume.all_bullets():
        raise HTTPException(status_code=409, detail="简历内容为空，无法导出")
    name = session.resume.basics.name or "candidate"
    if format == "pdf":
        if variant == "diff":
            raise HTTPException(status_code=400, detail="PDF 仅支持 optimized / original")
        data = exporter.render_pdf(session.resume, variant)
        filename = exporter.safe_filename(name, "pdf")
        media = "application/pdf"
    elif format == "html":
        data = exporter.render_html(session.resume, variant).encode("utf-8")
        filename = exporter.safe_filename(name, "html")
        media = "text/html; charset=utf-8"
    else:
        raise HTTPException(status_code=400, detail="format 仅支持 html | pdf")
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Content-Length": str(len(data)),
        },
    )


@router.get("/sessions/{sid}/preview")
async def preview(
    sid: str, user: dict = Depends(get_current_user), variant: str = "optimized"
) -> Response:
    """内联渲染，供前端 iframe 预览（不触发下载）。鉴权走 Cookie，iframe 也能带上。"""
    session = get_session(sid, user)
    html_doc = exporter.render_html(session.resume, variant)
    return Response(content=html_doc, media_type="text/html; charset=utf-8")
