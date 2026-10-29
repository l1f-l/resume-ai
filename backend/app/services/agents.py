"""多 Agent 编排：简历修改者（ResumeAgent）与面试官（InterviewerAgent）。

两个角色共享同一套 SSE 事件协议，靠「角色 + Prompt」切换，无需额外框架；
若后续要换 LangGraph，只需替换本文件的编排部分，事件协议与前端不用动。

降级策略（任务三）：
真实模型调用失败时，不抛 500、不中断 SSE，而是推一条 `warning`，再用内置
演示引擎把这一次请求做完，用户始终能拿到可用的结果。401/402 会整体熔断，
后续请求直接用演示引擎，避免每次都白等一次超时。
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from ..config import settings
from ..prompts import (
    ANALYZE,
    FEEDBACK,
    FOLLOW_UP,
    INTERVIEW_QUESTIONS,
    REPORT,
    REVISE,
    REWRITE,
    SYSTEM_INTERVIEWER,
    SYSTEM_RESUME_ARCHITECT,
)
from ..schemas import (
    AnswerFeedback,
    Diagnosis,
    InterviewQuestion,
    InterviewReport,
    ResumeDoc,
)
from . import mock_engine, nlp
from .llm import LLM, LLMError, parse_json_loose
from .state import Stage

log = logging.getLogger("agents")
Event = tuple[str, dict]


def _msg(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


class BaseAgent:
    role = "assistant"

    def __init__(self, llm: LLM | None = None) -> None:
        self.llm = llm or LLM()

    # -- 本地文本按打字机节奏流出 ---------------------------------------- #
    async def _type(self, text: str, delay: float | None = None) -> AsyncIterator[Event]:
        step = mock_engine.stream_delay() if delay is None else delay
        for chunk in mock_engine.chunk_text(text, 2):
            yield "token", {"text": chunk}
            if step > 0:
                await asyncio.sleep(step)

    # -- 真实模型流式 ---------------------------------------------------- #
    async def _llm_type(self, messages: list[dict], **kw) -> AsyncIterator[Event]:
        async for piece in self.llm.stream(messages, **kw):
            yield "token", {"text": piece}

    def _fallback_warning(self, exc: LLMError) -> Event:
        return "warning", {"message": self.llm.friendly(exc)}


# --------------------------------------------------------------------------- #
# 简历修改者
# --------------------------------------------------------------------------- #
class ResumeAgent(BaseAgent):
    role = "resume_optimizer"

    # ---------------------------- 诊断 ---------------------------------- #
    async def diagnose(self, resume: ResumeDoc, jd: str, resume_text: str) -> AsyncIterator[Event]:
        yield "phase", {"name": "analyze", "label": "正在比对 JD 与简历的关键词覆盖…"}

        dx: Diagnosis | None = None
        narrated = False

        if not self.llm.is_mock:
            try:
                async for ev in self._llm_type(
                    [
                        _msg("system", SYSTEM_RESUME_ARCHITECT),
                        _msg(
                            "user",
                            "只输出一段中文口语点评（2-3 句，不超过 100 字，不要分点、不要 Markdown）："
                            "告诉候选人这份简历和目标 JD 的匹配情况——先给一个带具体证据的亮点，"
                            "再指出最致命的短板，最后给一句可执行建议。\n\n"
                            f"JD：{jd[:1500]}\n\n简历：{resume_text[:4000]}",
                        ),
                    ],
                    temperature=0.4,
                    max_tokens=260,
                ):
                    narrated = True
                    yield ev

                raw = await self.llm.complete_json(
                    [
                        _msg("system", SYSTEM_RESUME_ARCHITECT),
                        _msg("user", ANALYZE.format(
                            jd=jd[:4000],
                            resume=resume.model_dump_json(exclude={"summary": {"optimized"}})[:6000],
                        )),
                    ],
                    temperature=0.25,
                    max_tokens=2400,
                )
                dx = _diagnosis_from(raw, resume)
                dx.retrieved_templates = self._templates(jd)
            except LLMError as exc:
                log.warning("diagnose fallback: %s", exc)
                yield self._fallback_warning(exc)
                dx = None

        if dx is None:
            dx = mock_engine.analyze(resume, jd, resume_text)
            if not narrated:
                async for ev in self._type(self._mock_narrative(dx)):
                    yield ev

        yield "diagnosis", dx.model_dump()
        yield "state", {"stage": Stage.DIAGNOSED}

    @staticmethod
    def _templates(jd: str) -> list:
        try:
            from .rag import store  # noqa: PLC0415

            return store.search(jd[:600], k=3)
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _mock_narrative(dx: Diagnosis) -> str:
        dims = sorted(dx.dimensions, key=lambda d: d.score)
        low, high = (dims[0], dims[-1]) if dims else (None, None)
        if not low or not high:
            return f"整体匹配度 {dx.match_score} 分，建议先补齐量化数据再看具体条目。"
        return (
            f"这份简历和 JD 的匹配度是 {dx.match_score} 分。{dx.strengths[0] if dx.strengths else ''}。"
            f"最拖后腿的是{low.name}（{low.score} 分）——{low.comment}。"
            f"先补 3 个数字，我把最关键的经历按 STAR 重写一遍。"
        )

    # ---------------------------- 追问 ---------------------------------- #
    async def ask(self, resume: ResumeDoc, gap, bullet_text: str) -> AsyncIterator[Event]:
        yield "phase", {"name": "clarify", "label": "正在整理需要你补充的量化数据…"}
        question = gap.question
        asked = False

        if not self.llm.is_mock:
            try:
                raw = await self.llm.complete_json(
                    [
                        _msg("system", SYSTEM_RESUME_ARCHITECT),
                        _msg("user", FOLLOW_UP.format(
                            asked=gap.topic,
                            topic=gap.topic,
                            bullet=bullet_text or gap.question,
                        )),
                    ],
                    temperature=0.55,
                    max_tokens=300,
                )
                question = str(raw.get("question") or question).strip()
                if len(question) < 6:
                    question = gap.question
                asked = True
            except LLMError as exc:
                yield self._fallback_warning(exc)

        if not asked:
            question = mock_engine.next_gap_question(gap, bullet_text)

        async for ev in self._type(question, delay=min(0.012, mock_engine.stream_delay())):
            yield ev
        yield "gap", {**gap.model_dump(), "question": question}

    # ---------------------------- 重写 ---------------------------------- #
    async def rewrite(
        self,
        resume: ResumeDoc,
        answers: dict[str, str],
        jd: str,
        answers_map: dict[str, str],
    ) -> AsyncIterator[Event]:
        yield "phase", {"name": "rewrite", "label": "正在按 STAR 法则重写经历…"}

        payload: dict | None = None
        narrated = False

        if not self.llm.is_mock:
            try:
                async for ev in self._llm_type(
                    [
                        _msg("system", SYSTEM_RESUME_ARCHITECT),
                        _msg(
                            "user",
                            "只输出一段中文口语总结（2 句内，80 字内，不要分点）：说明你把简历改成了什么样，"
                            "点出一个最关键的改动。不要复述条目。\n\n"
                            f"JD：{jd[:1200]}",
                        ),
                    ],
                    temperature=0.4,
                    max_tokens=200,
                ):
                    narrated = True
                    yield ev

                raw = await self.llm.complete_json(
                    [
                        _msg("system", SYSTEM_RESUME_ARCHITECT),
                        _msg("user", REWRITE.format(
                            keywords="、".join(nlp.extract_keywords(jd, top=8)),
                            jd=jd[:3000],
                            resume=resume.model_dump_json()[:8000],
                            answers=nlp.split_qa_pairs(answers_map),
                        )),
                    ],
                    temperature=0.4,
                    max_tokens=3000,
                )
                payload = raw  # complete_json 已经解析成 dict
            except LLMError as exc:
                log.warning("rewrite fallback: %s", exc)
                yield self._fallback_warning(exc)
                payload = None

        if payload is None:
            payload = mock_engine.rewrite(resume, answers, jd)
            if not narrated:
                narrative = "重写完成。我把「负责…」改成了「主导…」，每条都补上了动作和结果；"
                narrative += f"共重写 {len(payload['bullets'])} 条经历要点，摘要与技能行也按 JD 重排了。"
                async for ev in self._type(narrative):
                    yield ev

        payload = _normalize_rewrite(payload, resume, jd=jd)
        yield "rewrite", payload
        yield "state", {"stage": Stage.OPTIMIZED}

    # ---------------------------- 继续调整 ------------------------------ #
    async def revise(self, resume: ResumeDoc, instruction: str) -> AsyncIterator[Event]:
        yield "phase", {"name": "revise", "label": "正在按你的要求微调…"}
        payload: dict | None = None

        if not self.llm.is_mock:
            try:
                raw = await self.llm.complete_json(
                    [
                        _msg("system", SYSTEM_RESUME_ARCHITECT),
                        _msg("user", REVISE.format(
                            instruction=instruction[:400],
                            resume=resume.model_dump_json()[:8000],
                        )),
                    ],
                    temperature=0.4,
                )
                payload = raw  # complete_json 已经解析成 dict
            except LLMError as exc:
                yield self._fallback_warning(exc)

        if payload is None:
            payload = mock_engine.revision(resume, instruction)

        async for ev in self._type("已按你的要求更新，具体改动见右侧。", delay=0.008):
            yield ev

        payload = _normalize_rewrite(payload, resume, allow_partial=True)
        yield "rewrite", payload


def _diagnosis_from(raw: str | dict, resume: ResumeDoc) -> Diagnosis:
    data = parse_json_loose(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise LLMError("诊断结果不是对象", kind="parse")
    try:
        dx = Diagnosis.model_validate(
            {
                "match_score": data.get("match_score", 0),
                "verdict": data.get("verdict", ""),
                "dimensions": data.get("dimensions") or [],
                "requirement_matches": data.get("requirement_matches") or [],
                "missing_keywords": data.get("missing_keywords") or [],
                "strengths": data.get("strengths") or [],
                "risks": data.get("risks") or [],
                "gap_questions": data.get("gap_questions") or [],
            }
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"诊断 JSON 结构不符合约定：{exc}", kind="parse") from exc

    # 补齐 gap id / 关联 bullet；模型漏掉的追问用规则补上
    bullets = [b for b in resume.all_bullets() if b.original.strip()]
    for i, g in enumerate(dx.gap_questions, start=1):
        g.id = g.id or f"g{i}"
        g.question = _strip_internal_ids(g.question)
        if not g.bullet_id and i <= len(bullets):
            g.bullet_id = bullets[i - 1].id
    if len(dx.gap_questions) < 3:
        extra = mock_engine.analyze(resume, "", _resume_text(resume)).gap_questions
        dx.gap_questions = (dx.gap_questions + extra)[:5]
    return dx


def _strip_internal_ids(text: str) -> str:
    """模型有时会把 b1/proj1 这类内部编号写进追问，用户看不懂。"""
    import re

    cleaned = re.sub(r"\b(?:proj|exp|edu|b|g)\d{1,3}\b", "", text or "")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ，,、")
    return cleaned or text


def _resume_text(resume: ResumeDoc) -> str:
    parts = [resume.summary.original, resume.skills.original]
    parts += [b.original for b in resume.all_bullets()]
    return "\n".join(p for p in parts if p)


def _merge_skills(resume: ResumeDoc, jd: str, model_text: str = "") -> str:
    """技能行由代码合并，不让模型自由发挥：避免编造技能、也避免重复/截断的脏词。"""
    import re

    def split(text: str) -> list[str]:
        return [x.strip() for x in re.split(r"[,，、·|]", text or "") if x.strip()]

    origin = split(resume.skills.original)
    origin_low = {x.lower() for x in origin}
    # 模型只负责排序，不允许新增原简历没有的技能
    kept: list[str] = []
    for item in split(model_text) + origin:
        if item.lower() in origin_low and item.lower() not in {k.lower() for k in kept}:
            kept.append(item)
    if not kept:
        kept = origin

    def already(kw: str) -> bool:
        low = kw.lower()
        return any(low in item.lower() or item.lower() in low for item in kept)

    jd_kw = nlp.extract_keywords(jd, top=14) if jd else []
    corpus = _resume_text(resume).lower()
    for kw in jd_kw:
        # 「A/B」与「A/B测试」算同一个技能，避免重复
        if kw.lower() in corpus and not already(kw):
            kept.append(kw)

    if jd_kw:
        jd_low = {k.lower() for k in jd_kw}
        kept.sort(key=lambda x: 0 if x.lower() in jd_low else 1)
    return " · ".join(kept[:14])


def _normalize_rewrite(payload: dict, resume: ResumeDoc, allow_partial: bool = False,
                       jd: str = "") -> dict:
    """把模型输出对齐到前端需要的形状：bullets 必须带 id / star / metrics，且不漏条。"""
    valid_ids = {b.id for b in resume.all_bullets()}
    out: list[dict] = []
    for item in payload.get("bullets") or []:
        if not isinstance(item, dict):
            continue
        bid = str(item.get("id") or "")
        if bid not in valid_ids:
            continue
        star = item.get("star") or {}
        text = str(item.get("optimized") or "").strip()
        if not text:
            continue
        out.append(
            {
                "id": bid,
                "optimized": text,
                "star": {
                    "situation": str(star.get("situation") or ""),
                    "task": str(star.get("task") or ""),
                    "action": str(star.get("action") or ""),
                    "result": str(star.get("result") or ""),
                },
                "metrics": [str(m) for m in (item.get("metrics") or [])][:6]
                or nlp.extract_metrics(text),
            }
        )
    if not allow_partial:
        covered = {b["id"] for b in out}
        for b in resume.all_bullets():
            if b.original.strip() and b.id not in covered:
                text, star, metrics = mock_engine.optimize_bullet(b.original, "")
                out.append({"id": b.id, "optimized": text, "star": star.model_dump(), "metrics": metrics})
    summary = payload.get("summary") or {}
    skills = payload.get("skills") or {}
    return {
        "summary": {
            "optimized": str(summary.get("optimized") or resume.summary.optimized or ""),
            "star": summary.get("star") or {},
        },
        "skills": {"optimized": _merge_skills(resume, jd, str(skills.get("optimized") or ""))},
        "bullets": out,
    }


# --------------------------------------------------------------------------- #
# 面试官
# --------------------------------------------------------------------------- #
class InterviewerAgent(BaseAgent):
    role = "interviewer"

    async def make_questions(self, resume: ResumeDoc, jd: str, hits: list | None = None) -> AsyncIterator[Event]:
        yield "phase", {"name": "interview", "label": "正在根据简历生成 5 道面试题…"}
        questions: list[InterviewQuestion] = []

        if not self.llm.is_mock:
            template_hint = ""
            if hits:
                template_hint = "可参考的面试组织范式：\n" + "\n".join(
                    f"- {h.title}: {h.snippet[:120]}" for h in hits[:2]
                )
            try:
                raw = await self.llm.complete_json(
                    [
                        _msg("system", SYSTEM_INTERVIEWER),
                        _msg("user", INTERVIEW_QUESTIONS.format(
                            jd=jd[:2500],
                            resume=resume.model_dump_json()[:6000],
                            template_hint=template_hint,
                        )),
                    ],
                    temperature=0.5,
                    max_tokens=2200,
                )
                for i, q in enumerate((raw.get("questions") or [])[:5], start=1):
                    questions.append(_question_from(q, i))
            except LLMError as exc:
                yield self._fallback_warning(exc)

        if len(questions) < 5:
            questions = mock_engine.interview_questions(resume, jd, hits)

        intro = (
            f"面试开始。我会围绕你简历里的项目连续追问 5 轮，"
            f"每题都会现场打分并给改进建议。第一题：{questions[0].question}"
        )
        async for ev in self._type(intro):
            yield ev

        for q in questions:
            if not q.key_points:
                q.key_points = ["背景与目标", "具体动作", "量化结果", "过程中的取舍"]
        yield "questions", {"questions": [q.model_dump() for q in questions]}
        yield "question", {"question": questions[0].model_dump()} if questions else {"question": None}
        yield "state", {"stage": Stage.INTERVIEWING}

    async def ask_question(self, q: InterviewQuestion, idx: int) -> AsyncIterator[Event]:
        lead = f"第 {idx} 题：{q.question}"
        async for ev in self._type(lead):
            yield ev
        yield "question", {"question": q.model_dump()}

    async def evaluate(self, q: InterviewQuestion, answer: str) -> AsyncIterator[Event]:
        yield "phase", {"name": "score", "label": "正在评估你的回答…"}
        fb: AnswerFeedback | None = None

        if not self.llm.is_mock:
            try:
                raw = await self.llm.complete_json(
                    [
                        _msg("system", SYSTEM_INTERVIEWER),
                        _msg("user", FEEDBACK.format(
                            question=q.question,
                            key_points="、".join(q.key_points),
                            answer=answer[:2000],
                        )),
                    ],
                    temperature=0.3,
                    max_tokens=1200,
                )
                fb = _feedback_from(raw, q, answer)
            except LLMError as exc:
                yield self._fallback_warning(exc)

        if fb is None:
            fb = mock_engine.feedback(q, answer)

        async for ev in self._type(f"{fb.score} 分。{fb.verdict}"):
            yield ev
        yield "feedback", fb.model_dump()

    async def wrap_up(self, feedbacks: list[AnswerFeedback], questions: list[InterviewQuestion]) -> AsyncIterator[Event]:
        yield "phase", {"name": "report", "label": "正在生成面试复盘…"}
        rp: InterviewReport | None = None

        if not self.llm.is_mock and feedbacks:
            records = "\n".join(
                f"{i + 1}. 题：{q.question}\n   答：{f.answer[:200]}\n   分：{f.score}"
                for i, (q, f) in enumerate(zip(questions, feedbacks))
            )
            try:
                raw = await self.llm.complete_json(
                    [
                        _msg("system", SYSTEM_INTERVIEWER),
                        _msg("user", REPORT.format(records=records[:4000])),
                    ],
                    temperature=0.3,
                    max_tokens=1200,
                )
                rp = _report_from(raw, feedbacks, questions)
            except LLMError as exc:
                yield self._fallback_warning(exc)

        if rp is None:
            rp = mock_engine.report(feedbacks, questions)

        async for ev in self._type(f"面试结束，综合得分 {rp.overall} 分（{rp.level}）。{rp.summary}"):
            yield ev
        yield "report", rp.model_dump()
        yield "state", {"stage": Stage.REVIEWED}


# --------------------------------------------------------------------------- #
# LLM 输出 → 领域模型（统一做一次校验与兜底）
# --------------------------------------------------------------------------- #
def _question_from(q: dict, i: int) -> InterviewQuestion:
    kind = q.get("kind") if q.get("kind") in {"behavioral", "technical", "situational", "culture", "pressure"} else "behavioral"
    difficulty = q.get("difficulty") if q.get("difficulty") in {"easy", "medium", "hard"} else "medium"
    return InterviewQuestion(
        id=str(q.get("id") or f"q{i}"),
        index=i,
        kind=kind,
        difficulty=difficulty,
        question=_strip_internal_ids(str(q.get("question") or ""))[:300],
        intent=_strip_internal_ids(str(q.get("intent") or ""))[:200],
        key_points=[str(p)[:60] for p in (q.get("key_points") or [])][:4],
    )


def _feedback_from(data: dict, q: InterviewQuestion, answer: str) -> AnswerFeedback:
    fb = AnswerFeedback(
        question_id=q.id,
        answer=answer,
        score=max(0, min(100, int(data.get("score") or 0))),
        verdict=_strip_internal_ids(str(data.get("verdict") or ""))[:200],
        scores=[
            {"name": str(s.get("name"))[:20], "score": max(0, min(100, int(s.get("score") or 0)))}
            for s in (data.get("scores") or []) if isinstance(s, dict)
        ][:4],
        strengths=[str(x)[:80] for x in (data.get("strengths") or [])][:3],
        improvements=[_strip_internal_ids(str(x))[:100] for x in (data.get("improvements") or [])][:3],
        missing_key_points=[str(x)[:60] for x in (data.get("missing_key_points") or [])][:3],
        reference_answer=_strip_internal_ids(str(data.get("reference_answer") or ""))[:600],
    )
    if not fb.scores:
        fb.scores = mock_engine.feedback(q, answer).scores
    if not fb.reference_answer:
        fb.reference_answer = mock_engine.feedback(q, answer).reference_answer
    return fb


def _report_from(data: dict, feedbacks: list[AnswerFeedback], questions: list[InterviewQuestion]) -> InterviewReport:
    rp = InterviewReport(
        overall=max(0, min(100, int(data.get("overall") or 0))),
        level=str(data.get("level") or ""),
        by_dimension=[
            {"name": str(s.get("name"))[:20], "score": max(0, min(100, int(s.get("score") or 0)))}
            for s in (data.get("by_dimension") or []) if isinstance(s, dict)
        ][:5],
        summary=str(data.get("summary") or "")[:400],
        advice=[str(x)[:120] for x in (data.get("advice") or [])][:4],
    )
    fallback = mock_engine.report(feedbacks, questions)
    if not rp.overall:
        rp.overall = fallback.overall
    if not rp.level:
        rp.level = fallback.level
    if not rp.by_dimension:
        rp.by_dimension = fallback.by_dimension
    if not rp.summary:
        rp.summary = fallback.summary
    if not rp.advice:
        rp.advice = fallback.advice
    return rp


__all__ = ["ResumeAgent", "InterviewerAgent", "settings", "log"]
