"""会话与状态（SQLite 持久化，重启不丢）。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import settings
from .db import Database
from .schemas import (
    AnswerFeedback,
    ChatMessage,
    Diagnosis,
    GapQuestion,
    InterviewQuestion,
    InterviewReport,
    ResumeDoc,
    SessionSummary,
    StarBreakdown,
)
from .services.state import Stage, StateMachine


@dataclass
class Session:
    id: str
    user_id: str = ""                                              # 归属用户（Pro：强绑定）
    job_id: str = ""                                               # 当前选中的岗位（空=手填 JD）
    file_name: str = ""
    pages: int = 0
    chars: int = 0
    resume_text: str = ""
    jd: str = ""
    resume: ResumeDoc = field(default_factory=ResumeDoc)
    diagnosis: Diagnosis | None = None
    answers: dict[str, str] = field(default_factory=dict)          # bullet_id -> 用户补充的量化数据
    qa_pairs: list[tuple[str, str]] = field(default_factory=list)  # 追问/回答原文
    questions: list[InterviewQuestion] = field(default_factory=list)
    feedbacks: list[AnswerFeedback] = field(default_factory=list)
    report: InterviewReport | None = None
    cursor: int = 0                                                # 面试进行到第几题
    messages: list[ChatMessage] = field(default_factory=list)
    machine: StateMachine = field(default_factory=StateMachine)
    llm_mode: str = "mock"
    parse_meta: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    # --- 运行时（不落库） ---
    _autosave: Callable[["Session"], None] | None = field(default=None, repr=False, compare=False)
    _persisted_stage: str = field(default="", repr=False, compare=False)

    # ---------------------------------------------------------------- #
    @property
    def stage(self) -> str:
        return self.machine.stage

    def _touch(self) -> None:
        """任何影响恢复的状态变更都立刻落盘。"""
        if self._autosave:
            self._autosave(self)

    def advance(self, stage: str) -> str:
        result = self.machine.to(stage)
        self._touch()
        return result

    # ---------------------------------------------------------------- #
    def pending_gaps(self) -> list[GapQuestion]:
        if not self.diagnosis:
            return []
        return [g for g in self.diagnosis.gap_questions if not g.answered]

    def current_gap(self) -> GapQuestion | None:
        pending = self.pending_gaps()
        return pending[0] if pending else None

    def gap_progress(self) -> tuple[int, int]:
        if not self.diagnosis:
            return 0, 0
        total = len(self.diagnosis.gap_questions)
        return total - len(self.pending_gaps()), total

    def mark_answered(self, answer: str) -> GapQuestion | None:
        gap = self.current_gap()
        if not gap:
            return None
        gap.answer = answer
        gap.answered = True
        if answer.strip():
            self.answers[gap.bullet_id] = answer.strip()
        self.qa_pairs.append((gap.question, answer))
        self._touch()
        return gap

    # ---------------------------------------------------------------- #
    def add_message(self, role: str, content: str) -> None:
        self.messages.append(ChatMessage(role=role, content=content, created_at=_now()))
        if len(self.messages) > 200:
            self.messages = self.messages[-200:]
        self._touch()

    def current_question(self) -> InterviewQuestion | None:
        if 0 <= self.cursor < len(self.questions):
            return self.questions[self.cursor]
        return None

    def summary(self) -> SessionSummary:
        answered, total = self.gap_progress()
        report = None
        if self.job_id:  # 岗位池模式下带上雷达图快照，前端刷新可恢复
            from .matches import match_store  # noqa: PLC0415 - 避免模块级循环依赖

            report = match_store.current_report(self.id)
        return SessionSummary(
            id=self.id,
            stage=self.stage,
            job_id=self.job_id,
            file_name=self.file_name,
            pages=self.pages,
            chars=self.chars,
            jd=self.jd,
            llm_mode=self.llm_mode,
            parse_meta=self.parse_meta,
            match_score=(self.diagnosis.match_score if self.diagnosis else 0),
            answered_gaps=answered,
            total_gaps=total,
            interview_total=len(self.questions),
            interview_answered=len(self.feedbacks),
            resume=self.resume,
            diagnosis=self.diagnosis,
            match_report=report,
            questions=self.questions,
            feedbacks=self.feedbacks,
            report=self.report,
            messages=self.messages,
        )


def _now() -> str:
    return time.strftime("%H:%M:%S")


# --------------------------------------------------------------------------- #
# 持久化
# --------------------------------------------------------------------------- #
def _dump(obj: Any) -> str | None:
    if obj is None:
        return None
    return obj.model_dump_json() if hasattr(obj, "model_dump_json") else str(obj)


class SessionStore:
    """对外接口保持不变，内部换成 SQLite；每次 get 都从库里重建，天然支持重启恢复。"""

    def __init__(self, db_path: str | None = None) -> None:
        self.db = Database(db_path or settings.db_path)

    # ---------------------------------------------------------------- #
    def create(self, **kw: Any) -> Session:
        sid = uuid.uuid4().hex[:12]
        s = Session(id=sid, **kw)
        s._autosave = self.save
        self.save(s)
        return s

    def save(self, s: Session) -> None:
        import json

        row = {
            "id": s.id,
            "user_id": s.user_id or None,
            "job_id": s.job_id or None,
            "stage": s.stage,
            "file_name": s.file_name,
            "pages": s.pages,
            "chars": s.chars,
            "resume_text": s.resume_text,
            "jd_text": s.jd,
            "resume_json": s.resume.model_dump_json(),
            "diagnosis_json": _dump(s.diagnosis),
            "answers_json": json.dumps(s.answers, ensure_ascii=False),
            "qa_json": json.dumps(s.qa_pairs, ensure_ascii=False),
            "questions_json": json.dumps([q.model_dump() for q in s.questions], ensure_ascii=False),
            "feedbacks_json": json.dumps([f.model_dump() for f in s.feedbacks], ensure_ascii=False),
            "report_json": _dump(s.report),
            "messages_json": json.dumps([m.model_dump() for m in s.messages], ensure_ascii=False),
            "cursor": s.cursor,
            "llm_mode": s.llm_mode,
            "parse_meta_json": json.dumps(s.parse_meta, ensure_ascii=False),
            "created_at": s.created_at,
            "updated_at": time.time(),
        }
        self.db.upsert(row)
        if s._persisted_stage != s.stage:
            self.db.add_stage(s.id, s.stage)
            s._persisted_stage = s.stage

    def get(self, sid: str) -> Session | None:
        raw = self.db.load(sid)
        if not raw:
            return None
        import json

        def _json(key: str, default: Any) -> Any:
            val = raw.get(key)
            if not val or val == "null":
                return default
            try:
                return json.loads(val)
            except (TypeError, ValueError):
                return default

        def _model(key: str, cls):
            val = raw.get(key)
            if not val or val == "null":
                return None
            return cls.model_validate_json(val)

        s = Session(
            id=raw["id"],
            user_id=raw.get("user_id") or "",
            job_id=raw.get("job_id") or "",
            file_name=raw.get("file_name") or "",
            pages=int(raw.get("pages") or 0),
            chars=int(raw.get("chars") or 0),
            resume_text=raw.get("resume_text") or "",
            jd=raw.get("jd_text") or "",
            resume=ResumeDoc.model_validate_json(raw["resume_json"]) if raw.get("resume_json") else ResumeDoc(),
            diagnosis=_model("diagnosis_json", Diagnosis),
            answers=_json("answers_json", {}),
            qa_pairs=[tuple(x) for x in _json("qa_json", [])],
            questions=[InterviewQuestion(**q) for q in _json("questions_json", [])],
            feedbacks=[AnswerFeedback(**f) for f in _json("feedbacks_json", [])],
            report=_model("report_json", InterviewReport),
            cursor=int(raw.get("cursor") or 0),
            messages=[ChatMessage(**m) for m in _json("messages_json", [])],
            machine=StateMachine(raw["stage"]),
            llm_mode=raw.get("llm_mode") or "mock",
            parse_meta=_json("parse_meta_json", {}),
            created_at=float(raw.get("created_at") or time.time()),
        )
        s._persisted_stage = raw["stage"]
        s.machine.history = self.db.stages(sid) or [raw["stage"]]
        s._autosave = self.save
        return s

    def drop(self, sid: str) -> None:
        self.db.delete(sid)

    def list_recent(self, limit: int = 20, user_id: str | None = None) -> list[dict[str, Any]]:
        return self.db.list_recent(limit, user_id=user_id)

    def __len__(self) -> int:  # pragma: no cover
        return self.db.count()


store = SessionStore()


# --------------------------------------------------------------------------- #
def apply_rewrite(session: Session, payload: dict) -> ResumeDoc:
    """把重写结果写回结构化简历（幂等：同一份 payload 重复应用结果一致）。"""
    resume = session.resume
    by_id = {b.id: b for b in resume.all_bullets()}
    for item in payload.get("bullets") or []:
        b = by_id.get(str(item.get("id")))
        if not b:
            continue
        text = (item.get("optimized") or "").strip()
        if not text:
            continue
        b.optimized = text
        b.changed = text != b.original.strip()
        star = item.get("star") or {}
        if isinstance(star, dict) and any(star.values()):
            b.star = StarBreakdown(**{k: str(star.get(k) or "") for k in ("situation", "task", "action", "result")})
        if item.get("metrics"):
            b.metrics = [str(m) for m in item["metrics"]][:6]

    summary = (payload.get("summary") or {}).get("optimized")
    if summary:
        resume.summary.optimized = summary
        resume.summary.changed = True
    skills = (payload.get("skills") or {}).get("optimized")
    if skills:
        resume.skills.optimized = skills
        resume.skills.changed = True
    session._touch()
    return resume


def reset_interview(session: Session) -> None:
    session.questions = []
    session.feedbacks = []
    session.report = None
    session.cursor = 0
    if session.stage in (Stage.INTERVIEWING, Stage.REVIEWED):
        session.machine = StateMachine(Stage.OPTIMIZED)
    session._touch()
