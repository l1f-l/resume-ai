"""双向匹配路由：简历 → Top3 推荐，岗位 → 匹配度报告（SSE）。"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..config import settings
from ..deps import current_session
from ..jobs import job_store
from ..matches import match_store
from ..runtime import llm
from ..schemas import JobBrief
from ..services import matching, mock_engine
from ..services.state import Stage
from ..session import Session
from ..sse import sse_stream

log = logging.getLogger("matching.api")
router = APIRouter(prefix="/sessions", tags=["matching"])


@router.post("/{sid}/match")
async def match_top3(session: Session = Depends(current_session)) -> dict:
    """提取简历特征 → 岗位池语义召回 → 规则预排 → 大模型精排，返回 Top3。"""
    items, backend, note = await matching.recommend(session, llm)
    if items:
        match_store.save_ranking(session.user_id, session.id, items)
    return {
        "session_id": session.id,
        "items": [i.model_dump() for i in items],
        "backend": backend,
        "pool_size": job_store.count(),
        "note": note,
    }


@router.get("/{sid}/matches")
async def list_matches(session: Session = Depends(current_session)) -> dict:
    """恢复用：已产生的推荐位与报告状态。"""
    return {
        "session_id": session.id,
        "job_id": session.job_id,
        "items": match_store.list_ranking(session.id),
        "pool_size": job_store.count(),
    }


@router.post("/{sid}/match/{job_id}")
async def match_report(
    job_id: str, session: Session = Depends(current_session)
) -> StreamingResponse:
    """针对具体岗位生成匹配度诊断（雷达图 + 技能缺口），并接入原有追问流程。"""
    from fastapi import HTTPException

    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")
    if session.stage not in (Stage.PARSED, Stage.DIAGNOSED):
        raise HTTPException(
            status_code=409,
            detail="已进入追问/优化阶段，如需更换目标岗位请重新上传简历",
        )

    async def gen():
        yield "phase", {"name": "match", "label": f"正在比对「{job['title']}」的岗位要求与你的简历…"}
        report, note = await matching.build_report(session, job, llm)
        if note:
            yield "warning", {"message": note}

        # 结构化 JSON 无法边生成边解析，这里用打字机回放结论，前端体验一致
        narrative = _narrative(report, job)
        delay = mock_engine.stream_delay()
        for chunk in mock_engine.chunk_text(narrative, 3):
            yield "token", {"text": chunk}
            if delay > 0:
                await asyncio.sleep(delay)

        match_store.save_report(session.user_id, session.id, report)

        # 灌入岗位上下文，并把报告映射成原有 Diagnosis，后续追问/重写链路零改动续跑
        session.job_id = job["id"]
        session.jd = job["jd_text"]
        session.diagnosis = matching.to_diagnosis(report)
        session.advance(Stage.DIAGNOSED)
        session.add_message(
            "assistant",
            f"已按「{job['company']} · {job['title']}」的岗位要求完成匹配诊断，"
            f"匹配度 {report.match_score} 分。{report.verdict}",
        )

        # 事件名与面试的 report 区分开，前端两条流可以共用同一个消费循环
        yield "match_report", {**report.model_dump(), "job": JobBrief(
            **{k: job.get(k) for k in JobBrief.model_fields if k in job}
        ).model_dump()}
        yield "state", {"stage": session.stage, "label": Stage.LABELS[session.stage]}
        yield "session", session.summary().model_dump()

    return sse_stream(gen(), session)


def _narrative(report, job: dict) -> str:
    parts = [f"匹配度 {report.match_score} 分。{report.verdict}"]
    if report.matched_skills:
        parts.append(f"命中要求：{'、'.join(report.matched_skills[:5])}。")
    if report.skill_gap:
        gaps = "、".join(g.skill for g in report.skill_gap[:3])
        parts.append(f"主要缺口：{gaps}。")
    parts.append(f"接下来我会针对「{job['title']}」补问几个关键数字，再把简历按 STAR 重写。")
    return " ".join(p for p in parts if p)
