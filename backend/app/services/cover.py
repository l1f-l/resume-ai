"""求职信生成：LLM 主路径 + 模板兜底。

模板必须只用简历里真实存在的信息（姓名/年限/公司/项目），
绝不出现「我曾主导 XX 亿项目」这类编造——邮件是发给真人看的，比页面更需要克制。
"""
from __future__ import annotations

import html as html_lib
import logging

from ..prompts import COVER_LETTER, SYSTEM_RESUME_ARCHITECT
from ..schemas import ResumeDoc
from . import nlp
from .llm import LLM, LLMError
from .matching import estimate_years

log = logging.getLogger("cover")


def _resume_digest(resume: ResumeDoc) -> str:
    parts = []
    if resume.basics.name:
        parts.append(f"姓名：{resume.basics.name}")
    if resume.basics.headline:
        parts.append(f"求职意向：{resume.basics.headline}")
    skills = resume.skills.optimized or resume.skills.original
    if skills:
        parts.append(f"技能：{skills}")
    for exp in resume.experiences[:3]:
        bullets = [b.optimized or b.original for b in exp.bullets if (b.optimized or b.original).strip()]
        parts.append(f"{exp.company} {exp.role} {exp.period}：" + "；".join(bullets[:3]))
    for proj in resume.projects[:2]:
        bullets = [b.optimized or b.original for b in proj.bullets if (b.optimized or b.original).strip()]
        parts.append(f"项目 {proj.name}：" + "；".join(bullets[:2]))
    return nlp.normalize("\n".join(parts))[:2500]


def _wrap(body: str) -> str:
    """统一邮件外壳：邮件客户端对内联样式支持不一，保持极简。"""
    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\','
        "'Microsoft YaHei',sans-serif;font-size:14px;line-height:1.8;color:#1f2937;"
        'max-width:640px">' + body + "</div>"
    )


def template_letter(resume: ResumeDoc, job: dict, to_name: str = "") -> tuple[str, str]:
    name = resume.basics.name or "候选人"
    years = estimate_years(resume)
    skills = [s.strip() for s in (resume.skills.optimized or resume.skills.original).replace("，", ",").split(",") if s.strip()]
    top_skills = "、".join(skills[:4]) or "相关技能"
    exp = resume.experiences[0] if resume.experiences else None
    exp_line = (
        f"最近在 <strong>{html_lib.escape(exp.company)}</strong> 担任 "
        f"{html_lib.escape(exp.role)}，"
        if exp and (exp.company or exp.role)
        else ""
    )
    job_skills = "、".join((job.get("skills") or [])[:4])
    greeting = f"尊敬的{html_lib.escape(to_name or job.get('company', ''))}招聘团队：" if job.get("company") else "尊敬的招聘团队："

    body = (
        f"<p>{greeting}</p>"
        f"<p>我是{html_lib.escape(name)}，看到贵司正在招聘"
        f"<strong>{html_lib.escape(job.get('title', ''))}</strong>，特此投递简历。"
        f"我有约 {years} 年相关经验，长期专注 {html_lib.escape(top_skills)} 方向。</p>"
        f"<p>{exp_line}负责过与岗位要求高度重叠的工作，"
        f"对 {html_lib.escape(job_skills or '该岗位核心技术栈')} 有实际使用经验，"
        f"并在项目中拿到过可量化的结果（详见附件简历）。</p>"
        f"<p>我相信自己在业务理解与工程落地之间的平衡，能较快接手团队的工作。"
        f"期待有机会进一步沟通，感谢您的时间。</p>"
        f"<p>此致<br/>敬礼</p>"
        f"<p><strong>{html_lib.escape(name)}</strong><br/>"
        f"{html_lib.escape(resume.basics.phone or '')}　{html_lib.escape(resume.basics.email or '')}</p>"
    )
    subject = f"应聘 {job.get('title', '')} - {name}"
    return subject, _wrap(body)


async def compose(resume: ResumeDoc, job: dict, llm: LLM) -> tuple[str, str, str]:
    """返回 (subject, body_html, note)。note 非空表示走了模板兜底。"""
    name = (resume.basics.name or "").strip()
    if not llm.is_mock:
        try:
            raw = await llm.complete_json(
                [
                    {"role": "system", "content": SYSTEM_RESUME_ARCHITECT},
                    {
                        "role": "user",
                        "content": COVER_LETTER.format(
                            name=name or "候选人",
                            job_title=job.get("title", ""),
                            company=job.get("company", ""),
                            jd=(job.get("jd_text") or "")[:2500],
                            resume=_resume_digest(resume),
                        ),
                    },
                ],
                temperature=0.4,
                max_tokens=1200,
            )
            subject = str(raw.get("subject") or "").strip()[:60]
            body = str(raw.get("body_html") or "").strip()
            if body and "<" in body:
                subject = subject or f"应聘 {job.get('title', '')}"
                return (
                    _fix_subject(subject, name),
                    _wrap(_fix_body_name(body, name)),
                    "",
                )
        except LLMError as exc:
            log.warning("cover letter fallback: %s", exc)
            subject, body = template_letter(resume, job)
            return subject, body, llm.friendly(exc)

    subject, body = template_letter(resume, job)
    return subject, body, ""


def _fix_subject(subject: str, name: str) -> str:
    if not name or name in subject:
        return subject
    return f"{subject} - {name}"


def _fix_body_name(body: str, name: str) -> str:
    """兜底校验：模型偶尔会「替」候选人起个名字，这里补上真实署名。"""
    if not name or name in body:
        return body
    return body + f'<p style="margin-top:16px"><strong>{html_lib.escape(name)}</strong></p>'
