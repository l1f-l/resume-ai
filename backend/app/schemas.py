"""领域模型。前端预览 / 红绿对比 / 面试记分板全部消费这里的结构。"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# 简历结构化模型
# --------------------------------------------------------------------------- #
class Basics(BaseModel):
    name: str = ""
    headline: str = ""  # 求职意向 / 一句话自我定位
    phone: str = ""
    email: str = ""
    location: str = ""
    links: list[str] = Field(default_factory=list)


class StarBreakdown(BaseModel):
    """STAR 四要素，便于前端做「结构拆解」展示。"""

    situation: str = ""  # S 背景
    task: str = ""       # T 任务
    action: str = ""     # A 动作
    result: str = ""     # R 结果（含量化）


class Bullet(BaseModel):
    id: str
    original: str
    optimized: str = ""
    star: Optional[StarBreakdown] = None
    metrics: list[str] = Field(default_factory=list)  # 抽取到的量化指标
    changed: bool = False

    @property
    def improved(self) -> bool:
        return self.changed and bool(self.optimized.strip())


class Experience(BaseModel):
    id: str
    company: str = ""
    role: str = ""
    period: str = ""
    location: str = ""
    bullets: list[Bullet] = Field(default_factory=list)


class ProjectItem(BaseModel):
    id: str
    name: str = ""
    role: str = ""
    period: str = ""
    bullets: list[Bullet] = Field(default_factory=list)


class Education(BaseModel):
    id: str
    school: str = ""
    degree: str = ""
    major: str = ""
    period: str = ""
    detail: str = ""


class ResumeDoc(BaseModel):
    basics: Basics = Field(default_factory=Basics)
    summary: Bullet = Field(default_factory=lambda: Bullet(id="summary", original=""))
    skills: Bullet = Field(default_factory=lambda: Bullet(id="skills", original=""))
    experiences: list[Experience] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    extras: list[str] = Field(default_factory=list)

    def all_bullets(self) -> list[Bullet]:
        out = [self.summary, self.skills]
        for exp in self.experiences:
            out.extend(exp.bullets)
        for proj in self.projects:
            out.extend(proj.bullets)
        return out

    def optimized_bullets(self) -> list[Bullet]:
        return [b for b in self.all_bullets() if b.optimized.strip()]


# --------------------------------------------------------------------------- #
# 诊断模型
# --------------------------------------------------------------------------- #
MatchLevel = Literal["strong", "partial", "missing"]


class DimensionScore(BaseModel):
    name: str
    score: int = Field(ge=0, le=100)
    comment: str = ""


class RequirementMatch(BaseModel):
    requirement: str
    evidence: str = ""
    level: MatchLevel = "partial"
    suggestion: str = ""


class GapQuestion(BaseModel):
    """AI 追问：专门挖「缺失的量化数据」。"""

    id: str
    topic: str            # 追问主题，如「GMV 提升幅度」
    question: str         # 面向用户的话术
    why: str = ""         # 为什么要问（写进简历的哪一条）
    bullet_id: str = ""   # 关联到哪一条 bullet
    answered: bool = False
    answer: str = ""


class Diagnosis(BaseModel):
    match_score: int = Field(ge=0, le=100, default=0)
    verdict: str = ""
    dimensions: list[DimensionScore] = Field(default_factory=list)
    requirement_matches: list[RequirementMatch] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    gap_questions: list[GapQuestion] = Field(default_factory=list)
    # 语义检索到的优秀模板（RAG 加分项）
    retrieved_templates: list["TemplateHit"] = Field(default_factory=list)


class TemplateHit(BaseModel):
    id: str
    title: str
    snippet: str = ""
    score: float = 0.0
    source: str = "chroma"


# --------------------------------------------------------------------------- #
# 面试模型
# --------------------------------------------------------------------------- #
QuestionKind = Literal["behavioral", "technical", "situational", "culture", "pressure"]


class InterviewQuestion(BaseModel):
    id: str
    index: int
    kind: QuestionKind = "behavioral"
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    question: str
    intent: str = ""
    key_points: list[str] = Field(default_factory=list)


class ScoreItem(BaseModel):
    name: str
    score: int = Field(ge=0, le=100)


class AnswerFeedback(BaseModel):
    question_id: str
    answer: str = ""
    score: int = Field(ge=0, le=100, default=0)
    verdict: str = ""
    scores: list[ScoreItem] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    reference_answer: str = ""
    missing_key_points: list[str] = Field(default_factory=list)


class InterviewReport(BaseModel):
    overall: int = 0
    level: str = ""
    by_dimension: list[ScoreItem] = Field(default_factory=list)
    summary: str = ""
    advice: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 岗位池与双向匹配
# --------------------------------------------------------------------------- #
class JobBrief(BaseModel):
    """岗位摘要：列表与推荐卡片共用，字段与 jobs 表对齐。"""

    id: str
    title: str
    company: str
    city: str = ""
    salary: str = ""
    salary_min: int = 0
    salary_max: int = 0
    seniority: str = ""
    industry: str = ""
    tags: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    jd_text: str = ""


class MatchItem(BaseModel):
    job: JobBrief
    rank: int = 0
    score: int = Field(ge=0, le=100, default=0)
    reason: str = ""
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)


class MatchResult(BaseModel):
    session_id: str
    items: list[MatchItem] = Field(default_factory=list)
    backend: str = "memory"
    note: str = ""


class SkillGap(BaseModel):
    """技能缺口：只允许出现在岗位池 skills / JD 里的技能，防止模型编造。"""

    skill: str
    importance: Literal["high", "medium", "low"] = "medium"
    have: bool = False
    evidence: str = ""
    suggestion: str = ""


class RadarItem(BaseModel):
    """雷达图一维：score 为候选人得分，benchmark 为该岗位的基准要求。"""

    dimension: str
    score: int = Field(ge=0, le=100, default=0)
    benchmark: int = Field(ge=0, le=100, default=0)
    comment: str = ""


class MatchReport(BaseModel):
    job_id: str = ""
    match_score: int = Field(ge=0, le=100, default=0)
    verdict: str = ""
    radar: list[RadarItem] = Field(default_factory=list)
    skill_gap: list[SkillGap] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    requirement_matches: list["RequirementMatch"] = Field(default_factory=list)
    gap_questions: list["GapQuestion"] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 投递
# --------------------------------------------------------------------------- #
ApplicationStatus = Literal["applied", "interviewing", "offer", "rejected", "withdrawn"]


class ApplicationOut(BaseModel):
    id: str
    job_id: str
    job_title: str = ""
    company: str = ""
    city: str = ""
    salary: str = ""
    status: ApplicationStatus = "applied"
    match_score: int = 0
    email_to: str = ""
    email_subject: str = ""
    mail_status: str = "pending"
    mail_error: str = ""
    attachment: str = ""
    note: str = ""
    created_at: float = 0
    updated_at: float = 0


# --------------------------------------------------------------------------- #
# 会话
# --------------------------------------------------------------------------- #
class Stage(str):
    pass


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: str = ""


class SessionSummary(BaseModel):
    """GET /api/session/{id} 的返回体，供前端刷新后恢复状态。"""

    id: str
    stage: str
    job_id: str = ""
    file_name: str = ""
    pages: int = 0
    chars: int = 0
    jd: str = ""
    llm_mode: str = "mock"
    parse_meta: dict = Field(default_factory=dict)
    match_score: int = 0
    answered_gaps: int = 0
    total_gaps: int = 0
    interview_total: int = 0
    interview_answered: int = 0
    resume: Optional[ResumeDoc] = None
    diagnosis: Optional[Diagnosis] = None
    match_report: Optional["MatchReport"] = None
    questions: list[InterviewQuestion] = Field(default_factory=list)
    feedbacks: list[AnswerFeedback] = Field(default_factory=list)
    report: Optional[InterviewReport] = None
    messages: list[ChatMessage] = Field(default_factory=list)


Diagnosis.model_rebuild()
MatchReport.model_rebuild()
SessionSummary.model_rebuild()
