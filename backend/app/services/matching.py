"""双向智能匹配：简历 → Top3 岗位，岗位 → 匹配度报告。

「不编造岗位」的三道闸门（需求第 5 条）：
1. Prompt 白名单：候选集以 job_id | 岗位 | 公司 | 技能 的紧凑格式喂给模型；
2. 服务端校验：模型返回的 job_id 逐个比对候选集，非白名单直接丢弃；
3. 数量兜底：丢弃后不足 3 条就按规则分补齐 —— 推荐结果永远来自岗位池。

技能缺口同样收紧：skill_gap[].skill 必须能在岗位 skills 或 JD 原文里找到，
否则剔除（沿用 agents._merge_skills「只允许重排、不允许新增」的思路）。
"""
from __future__ import annotations

import logging
import re

from ..jobs import job_store
from ..prompts import MATCH_REPORT, MATCH_TOP3, SYSTEM_MATCHER
from ..schemas import (
    Diagnosis,
    DimensionScore,
    GapQuestion,
    JobBrief,
    MatchItem,
    MatchReport,
    RadarItem,
    RequirementMatch,
    ResumeDoc,
    SkillGap,
)
from . import mock_engine, nlp
from .llm import LLM, LLMError

log = logging.getLogger("matching")

RADAR_DIMS = ("技能覆盖", "经验深度", "项目复杂度", "行业相关", "学历资质", "薪资匹配")


# --------------------------------------------------------------------------- #
# 简历特征
# --------------------------------------------------------------------------- #
def _bullets_text(bullets) -> str:
    return " ".join((b.optimized or b.original).strip() for b in bullets if (b.optimized or b.original).strip())


def resume_feature_text(resume: ResumeDoc) -> str:
    """把简历压成一段用于向量检索的特征文本（技能 + 项目经验为主）。"""
    parts: list[str] = []
    b = resume.basics
    if b.headline:
        parts.append(f"求职意向：{b.headline}")
    if b.location:
        parts.append(f"所在地：{b.location}")
    skills = resume.skills.optimized or resume.skills.original
    if skills:
        parts.append(f"技能：{skills}")
    summary = resume.summary.optimized or resume.summary.original
    if summary:
        parts.append(f"简介：{summary}")
    for exp in resume.experiences:
        parts.append(f"经历：{exp.company} {exp.role} {exp.period} {_bullets_text(exp.bullets)}")
    for proj in resume.projects:
        parts.append(f"项目：{proj.name} {proj.role} {_bullets_text(proj.bullets)}")
    for edu in resume.education:
        parts.append(f"教育：{edu.school} {edu.degree} {edu.major}")
    parts.extend(resume.extras)
    return nlp.normalize("\n".join(p for p in parts if p.strip()))


def _norm(text: str) -> str:
    """技能比对归一化：去空格/大小写/标点，让 Spring Boot 与 SpringBoot 等价。"""
    return re.sub(r"[\s\-_/·、,，.]+", "", (text or "").lower())


# 同一技能的常见写法差异：命中任一别名即视为具备（避免 A/B 实验 vs A/B测试 这类误判）
SYNONYMS: dict[str, tuple[str, ...]] = {
    "ab实验": ("ab", "abtest", "ab测试"),
    "ab测试": ("ab", "abtest", "ab实验"),
    "用户增长": ("增长",),
    "增长策略": ("增长",),
    "漏斗优化": ("漏斗",),
    "kubernetes": ("k8s",),
    "springboot": ("spring",),
    "spring": ("springboot",),
    "mysql": ("sql", "数据库"),
    "postgresql": ("sql", "数据库"),
    "redis": ("缓存",),
    "微服务": ("微服务", "服务拆分"),
    "性能优化": ("性能", "调优"),
    "数据分析": ("数据", "sql"),
    "需求管理": ("需求",),
    "竞品分析": ("竞品",),
    "项目管理": ("项目",),
}


def _skill_in(skill: str, blob_norm: str) -> bool:
    key = _norm(skill)
    if not key:
        return False
    if key in blob_norm:
        return True
    return any(alias and alias in blob_norm for alias in SYNONYMS.get(key, ()))


def compare_skills(resume_blob: str, job: dict) -> tuple[list[str], list[str]]:
    blob = _norm(resume_blob)
    matched, missing = [], []
    for skill in job.get("skills") or []:
        (matched if _skill_in(skill, blob) else missing).append(skill)
    return matched, missing


def estimate_years(resume: ResumeDoc) -> int:
    return mock_engine._estimate_years(resume)  # 复用已有实现，口径保持一致


def _seniority_fit(years: int, seniority: str) -> float:
    if not seniority:
        return 0.5
    table = {"校招": (0, 1), "1-3年": (1, 3), "3-5年": (3, 5), "5-10年": (5, 10)}
    lo, hi = table.get(seniority, (0, 99))
    if lo <= years <= hi:
        return 1.0
    gap = lo - years if years < lo else years - hi
    return max(0.0, 1.0 - gap / 4)


# --------------------------------------------------------------------------- #
# 简历 → Top3
# --------------------------------------------------------------------------- #
def _candidate_line(job: dict) -> str:
    skills = "、".join((job.get("skills") or [])[:8])
    return (
        f"{job['id']} | {job['title']} | {job['company']} | {job.get('city','')} | "
        f"{job.get('seniority','')} | {skills}"
    )


def _to_item(job: dict, score: int, reason: str, matched: list[str], missing: list[str],
             rank: int) -> MatchItem:
    return MatchItem(
        job=JobBrief(**{k: job.get(k) for k in JobBrief.model_fields if k in job}),
        rank=rank,
        score=max(0, min(100, score)),
        reason=reason,
        matched_skills=matched,
        missing_skills=missing,
    )


def _fallback_reason(job: dict, matched: list[str], missing: list[str]) -> str:
    if matched:
        head = "、".join(matched[:3])
        tail = f"；缺口在 {missing[0]}" if missing else "，技能面覆盖完整"
        return f"技能命中 {len(matched)}/{len(matched) + len(missing)}（{head}）{tail}。"
    return f"岗位方向与简历主线接近，但岗位要求的 {'、'.join(missing[:2])} 尚未体现。"


async def recommend(session, llm: LLM, *, recall: int = 12, shortlist: int = 6,
                    top: int = 3) -> tuple[list[MatchItem], str, str]:
    """返回 (items, backend, note)。任何失败都不抛异常，最差返回规则排序结果。"""
    blob = resume_feature_text(session.resume)
    if not blob.strip():
        return [], job_store.backend, "简历信息不足，无法提取技能与项目特征"

    hits = job_store.search_vector(blob, k=recall)
    if not hits:
        return [], job_store.backend, "岗位池为空，请先初始化岗位数据"

    years = estimate_years(session.resume)
    city = nlp.normalize(session.resume.basics.location or "")

    scored: list[tuple[float, dict, list[str], list[str]]] = []
    for job_id, vec in hits:
        job = job_store.get(job_id)
        if not job:
            continue
        matched, missing = compare_skills(blob, job)
        ratio = len(matched) / max(1, len(matched) + len(missing))
        city_fit = 1.0 if city and job.get("city") and nlp.normalize(job["city"]) in city else 0.35
        sen_fit = _seniority_fit(years, job.get("seniority", ""))
        fit = 0.6 * sen_fit + 0.4 * city_fit
        # hash 词袋余弦的绝对值偏低（典型 0.2-0.5），先归一化再参与加权，
        # 否则「完美命中」也只能拿到 50 分；归一化后各岗位之间仍有区分度。
        vec_scaled = min(1.0, vec / 0.45)
        score = 0.55 * ratio + 0.27 * vec_scaled + 0.18 * fit
        if ratio >= 0.55 and sen_fit >= 0.8:
            # 技能过半 + 年限对口：给一个随向量相关度浮动的下限（62~80），避免多条并列
            score = max(score, 0.62 + 0.18 * vec_scaled)
        scored.append((score, job, matched, missing))

    if not scored:
        return [], job_store.backend, "岗位池检索无结果"

    scored.sort(key=lambda t: -t[0])
    cands = scored[:shortlist]
    cand_map = {c[1]["id"]: c for c in cands}

    items: list[MatchItem] = []
    note = ""
    if not llm.is_mock:
        try:
            raw = await llm.complete_json(
                [
                    {"role": "system", "content": SYSTEM_MATCHER},
                    {
                        "role": "user",
                        "content": MATCH_TOP3.format(
                            candidates="\n".join(_candidate_line(c[1]) for c in cands),
                            resume=blob[:3000],
                        ),
                    },
                ],
                temperature=0.2,
                max_tokens=900,
            )
            items = _parse_items(raw, cand_map)
        except LLMError as exc:
            log.warning("top3 fallback: %s", exc)
            note = llm.friendly(exc)

    # 兜底 / 补齐：保证结果全部来自岗位池，且尽量凑满 3 条
    seen = {i.job.id for i in items}
    for score, job, matched, missing in cands:
        if len(items) >= top:
            break
        if job["id"] in seen:
            continue
        items.append(
            _to_item(job, round(score * 100), _fallback_reason(job, matched, missing),
                     matched, missing, len(items) + 1)
        )
        seen.add(job["id"])

    items = items[:top]
    for idx, item in enumerate(items, 1):
        item.rank = idx
    return items, job_store.backend, note


def _parse_items(raw: dict, cand_map: dict) -> list[MatchItem]:
    """白名单校验：非候选集里的 job_id 一律丢弃。"""
    out: list[MatchItem] = []
    for entry in (raw.get("items") or [])[:6]:
        if not isinstance(entry, dict):
            continue
        jid = str(entry.get("job_id") or "").strip()
        if jid not in cand_map:
            log.warning("dropped hallucinated job_id: %s", jid)
            continue
        _, job, rule_matched, rule_missing = cand_map[jid]
        try:
            score = int(float(entry.get("score") or 0))
        except (TypeError, ValueError):
            score = 0
        allowed = {_norm(s) for s in (job.get("skills") or [])}
        matched = [s for s in (entry.get("matched_skills") or []) if _norm(s) in allowed][:8]
        missing = [s for s in (entry.get("missing_skills") or []) if _norm(s) in allowed][:8]
        out.append(
            _to_item(
                job,
                score or round(cand_map[jid][0] * 100),  # 模型没给分就用该岗位自己的规则分
                str(entry.get("reason") or "").strip()[:120] or _fallback_reason(job, rule_matched, rule_missing),
                matched or rule_matched,
                missing or rule_missing,
                0,
            )
        )
    out.sort(key=lambda i: -i.score)
    return out[:3]


# --------------------------------------------------------------------------- #
# 岗位 → 匹配度报告
# --------------------------------------------------------------------------- #
def _allowed_skills(job: dict) -> set[str]:
    return {_norm(s) for s in (job.get("skills") or []) if _norm(s)}


def _in_jd(skill: str, jd_norm: str) -> bool:
    return _skill_in(skill, jd_norm)


async def build_report(session, job: dict, llm: LLM) -> tuple[MatchReport, str]:
    """返回 (report, note)。note 非空表示走了降级路径。"""
    blob = resume_feature_text(session.resume)
    rule_matched, rule_missing = compare_skills(blob, job)
    report: MatchReport | None = None
    note = ""

    if not llm.is_mock:
        try:
            raw = await llm.complete_json(
                [
                    {"role": "system", "content": SYSTEM_MATCHER},
                    {
                        "role": "user",
                        "content": MATCH_REPORT.format(
                            skills="、".join(job.get("skills") or []),
                            jd=job.get("jd_text", "")[:4000],
                            resume=session.resume.model_dump_json(
                                exclude={"summary": {"optimized"}}
                            )[:6000],
                        ),
                    },
                ],
                temperature=0.25,
                max_tokens=2400,
            )
            report = _report_from(raw, job, rule_matched, rule_missing)
        except LLMError as exc:
            log.warning("report fallback: %s", exc)
            note = llm.friendly(exc)

    if report is None:
        report = _mock_report(session, job, rule_matched, rule_missing)
    return report, note


def _report_from(raw: dict, job: dict, rule_matched: list[str],
                 rule_missing: list[str]) -> MatchReport:
    jd_norm = _norm(job.get("jd_text", ""))
    allowed = _allowed_skills(job)

    radar_raw = {str(r.get("dimension") or "").strip(): r for r in (raw.get("radar") or [])
                 if isinstance(r, dict)}
    radar: list[RadarItem] = []
    for dim in RADAR_DIMS:  # 固定 6 维、固定顺序，模型多给的丢掉、少给的补默认
        r = radar_raw.get(dim) or {}
        radar.append(
            RadarItem(
                dimension=dim,
                score=_int(r.get("score"), 60),
                benchmark=_int(r.get("benchmark"), 75),
                comment=str(r.get("comment") or "")[:80],
            )
        )

    gaps: list[SkillGap] = []
    for g in (raw.get("skill_gap") or [])[:10]:
        if not isinstance(g, dict):
            continue
        skill = str(g.get("skill") or "").strip()
        if not skill:
            continue
        if _norm(skill) not in allowed and not _in_jd(skill, jd_norm):
            log.warning("dropped invented skill: %s", skill)  # 不允许发明岗位没要求的技能
            continue
        imp = str(g.get("importance") or "medium").lower()
        gaps.append(
            SkillGap(
                skill=skill,
                importance=imp if imp in {"high", "medium", "low"} else "medium",
                have=bool(g.get("have")),
                evidence=str(g.get("evidence") or "")[:120],
                suggestion=str(g.get("suggestion") or "")[:160],
            )
        )
    if not gaps:
        gaps = [
            SkillGap(skill=s, importance="high" if i == 0 else "medium", have=False,
                     suggestion="补一个能体现该技能的实际项目案例，并写清规模与结果。")
            for i, s in enumerate(rule_missing[:4])
        ]

    matched = [s for s in (raw.get("matched_skills") or []) if _norm(s) in allowed] or rule_matched
    missing = [s for s in (raw.get("missing_skills") or []) if _norm(s) in allowed] or rule_missing

    reqs = []
    for r in (raw.get("requirement_matches") or [])[:8]:
        if not isinstance(r, dict):
            continue
        level = str(r.get("level") or "partial")
        reqs.append(
            RequirementMatch(
                requirement=str(r.get("requirement") or "")[:120],
                evidence=str(r.get("evidence") or "")[:200],
                level=level if level in {"strong", "partial", "missing"} else "partial",
                suggestion=str(r.get("suggestion") or "")[:120],
            )
        )

    gqs = []
    for i, g in enumerate((raw.get("gap_questions") or [])[:5], 1):
        if not isinstance(g, dict):
            continue
        q = str(g.get("question") or "").strip()
        if not q:
            continue
        gqs.append(
            GapQuestion(
                id=str(g.get("id") or f"g{i}"),
                topic=str(g.get("topic") or "")[:40],
                question=q[:200],
                why=str(g.get("why") or "")[:120],
                bullet_id=str(g.get("bullet_id") or ""),
            )
        )

    return MatchReport(
        job_id=job["id"],
        match_score=_int(raw.get("match_score"), 65),
        verdict=str(raw.get("verdict") or "")[:150],
        radar=radar,
        skill_gap=gaps,
        matched_skills=matched,
        missing_skills=missing,
        strengths=[str(s)[:120] for s in (raw.get("strengths") or [])][:4],
        risks=[str(s)[:120] for s in (raw.get("risks") or [])][:4],
        requirement_matches=reqs,
        gap_questions=gqs,
    )


def _mock_report(session, job: dict, matched: list[str], missing: list[str]) -> MatchReport:
    """无 Key / 降级时：复用演示引擎的诊断结果，映射成 6 维雷达。"""
    dx = mock_engine.analyze(session.resume, job.get("jd_text", ""), session.resume_text)
    dim_map = {d.name: d for d in dx.dimensions}

    def pick(name: str, fallback: int) -> DimensionScore:
        return dim_map.get(name) or DimensionScore(name=name, score=fallback, comment="")

    skill = pick("技能匹配", dx.match_score)
    depth = pick("经历深度", max(40, dx.match_score - 6))
    project = pick("量化成果", max(40, dx.match_score - 3))
    industry = pick("岗位贴合", max(40, dx.match_score - 8))
    edu = pick("表达结构", min(95, dx.match_score + 6))

    radar = [
        RadarItem(dimension="技能覆盖", score=skill.score, benchmark=85,
                  comment=skill.comment or f"命中 {len(matched)} 项岗位技能"),
        RadarItem(dimension="经验深度", score=depth.score, benchmark=80, comment=depth.comment),
        RadarItem(dimension="项目复杂度", score=project.score, benchmark=80,
                  comment=project.comment),
        RadarItem(dimension="行业相关", score=industry.score, benchmark=75,
                  comment=industry.comment or f"目标行业：{job.get('industry','')}"),
        RadarItem(dimension="学历资质", score=edu.score, benchmark=70, comment=edu.comment),
        RadarItem(dimension="薪资匹配", score=max(50, 100 - abs(70 - dx.match_score)),
                  benchmark=70, comment=f"岗位区间 {job.get('salary','')}"),
    ]

    return MatchReport(
        job_id=job["id"],
        match_score=dx.match_score,
        verdict=dx.verdict or "整体接近岗位要求，重点补技能缺口与量化成果。",
        radar=radar,
        skill_gap=[
            SkillGap(
                skill=s,
                importance="high" if i == 0 else "medium",
                have=False,
                evidence="简历未体现",
                suggestion="补一个能体现该技能的项目案例，写清规模、方案与结果。",
            )
            for i, s in enumerate(missing[:5])
        ],
        matched_skills=matched,
        missing_skills=missing,
        strengths=dx.strengths[:3],
        risks=dx.risks[:3],
        requirement_matches=dx.requirement_matches[:6],
        gap_questions=dx.gap_questions[:5],
    )


def to_diagnosis(report: MatchReport) -> Diagnosis:
    """把匹配报告转成原有 Diagnosis，让「追问 → STAR 重写 → 面试」链路零改动续跑。"""
    return Diagnosis(
        match_score=report.match_score,
        verdict=report.verdict,
        dimensions=[
            DimensionScore(name=r.dimension, score=r.score, comment=r.comment)
            for r in report.radar
        ],
        requirement_matches=report.requirement_matches,
        missing_keywords=report.missing_skills,
        strengths=report.strengths,
        risks=report.risks,
        gap_questions=report.gap_questions,
    )


def _int(value, default: int) -> int:
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return default
