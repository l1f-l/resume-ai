"""内置演示引擎（MOCK LLM）。

没有 DeepSeek Key 时，整个产品流程依然可跑通：诊断、追问、STAR 重写、面试评分
全部由确定性的规则产出。这不是「假数据」，而是一套可解释的启发式基线：
- 关键词命中率 / 量化密度 → 匹配分
- 缺失量化指标 → 生成追问
- 原文 + 用户补充数据 → 按 STAR 模板组装
- 回答结构 / 关键词覆盖 / 数据密度 → 打分
"""
from __future__ import annotations

import random
import re
from typing import Iterable

from ..config import settings
from ..schemas import (
    AnswerFeedback,
    DimensionScore,
    Diagnosis,
    GapQuestion,
    InterviewQuestion,
    InterviewReport,
    RequirementMatch,
    ResumeDoc,
    ScoreItem,
    StarBreakdown,
)
from . import nlp

WEAK_TO_STRONG = {
    "负责": "主导",
    "参与": "",
    "协助": "",
    "配合": "协同",
    "帮助": "驱动",
    "完成": "交付",
}

GOOD_VERBS = (
    "主导", "推动", "搭建", "重构", "量化", "牵头", "协同", "驱动", "交付",
    "落地", "整合", "设计", "优化", "提升", "降低", "缩短", "拓展", "推进",
    "完成", "承担", "建立", "输出", "拆解", "从 0", "从0",
)

GAP_TOPICS: tuple[tuple[str, str], ...] = (
    ("规模量级", "这件事的业务量级大概是多少？比如用户数、订单量、预算或团队人数"),
    ("结果幅度", "做完之后核心指标变化了多少？给我改造前后的两个数字就够"),
    ("效率提升", "流程优化后耗时或人力节省了多少？比如从几天压到几天"),
    ("成本收益", "它带来的成本节省或收入增长大概多少？年化金额也可以"),
    ("覆盖范围", "这套方案后来被多少人、多少团队复用了？"),
)

FILLERS = ("嗯", "那个", "然后就是", "大概吧", "还行", "差不多", "感觉", "可能是")

ACTION_LIBRARY = {
    "活动": "设计分层激励方案，联动多渠道组合触达",
    "分层": "按 RFM 分层配置差异化策略",
    "推送": "搭建自动化触达链路，分人群控制频次",
    "触达": "搭建自动化触达链路，分人群控制频次",
    "留存": "拆解留存漏斗，逐项定位流失节点",
    "转化": "拆解转化漏斗，按环节做 A/B 验证",
    "推荐": "重做召回与排序策略，按兴趣标签分发",
    "内容": "重做内容分发策略，按兴趣标签调整排序",
    "引导": "重构新手引导路径，用分层任务替代一次性弹窗",
    "新手": "重构新手引导路径，用分层任务替代一次性弹窗",
    "看板": "统一指标口径并沉淀自动化看板",
    "报表": "统一指标口径并沉淀自动化看板",
    "调研": "完成用户访谈与竞品拆解，输出优先级结论",
    "竞品": "完成用户访谈与竞品拆解，输出优先级结论",
    "跨部门": "建立里程碑与周会机制，前置对齐资源风险",
    "项目": "建立里程碑与周会机制，前置对齐资源风险",
    "系统": "重构核心链路并引入缓存与异步化改造",
    "平台": "抽象通用组件，供多业务线复用",
    "模型": "重做特征工程与召回策略，灰度上线验证",
    "预算": "推行零基预算，逐项复核投入产出",
    "团队": "重组分工与例会机制，目标拆解到人到周",
    "客户": "建立客户分层与续约预警机制",
}


def _short(text: str, n: int = 16) -> str:
    text = re.sub(r"\s+", "", text or "")
    return text if len(text) <= n else text[:n] + "…"


def _clamp(v: float, lo: int = 0, hi: int = 100) -> int:
    return int(max(lo, min(hi, round(v))))


# --------------------------------------------------------------------------- #
# 1. 诊断
# --------------------------------------------------------------------------- #
def analyze(resume: ResumeDoc, jd: str, resume_text: str) -> Diagnosis:
    from .rag import store  # 延迟导入，避免循环

    jd_keywords = nlp.extract_keywords(jd, top=24)
    corpus = " ".join(
        [resume_text, resume.skills.original, resume.summary.original]
        + [b.original for b in resume.all_bullets()]
    ).lower()
    matched = [k for k in jd_keywords if k.lower() in corpus]
    missing = [k for k in jd_keywords if k not in matched]

    bullets = [b for b in resume.all_bullets() if b.original.strip()]
    work_bullets = [b for e in resume.experiences for b in e.bullets if b.original.strip()]
    work_bullets += [b for p in resume.projects for b in p.bullets if b.original.strip()]
    scope = work_bullets or bullets
    quantified = [b for b in scope if nlp.has_metric(b.original)]
    weak = [b for b in scope if nlp.is_weak_phrase(b.original)]
    metric_ratio = len(quantified) / max(1, len(scope))
    weak_ratio = len(weak) / max(1, len(scope))
    skill_rate = len(matched) / max(1, len(jd_keywords))
    depth = min(1.0, (len(resume.experiences) * 0.2 + len(work_bullets) * 0.055))

    score = 34 + 30 * skill_rate + 17 * metric_ratio + 12 * depth + 7 * (1 - weak_ratio)
    score = _clamp(score, 32, 94)

    dims = [
        DimensionScore(
            name="技能匹配",
            score=_clamp(38 + 57 * skill_rate),
            comment=f"JD 关键词命中 {len(matched)}/{len(jd_keywords)}：{'、'.join(matched[:5]) or '几乎没有命中'}",
        ),
        DimensionScore(
            name="经历深度",
            score=_clamp(40 + 55 * depth),
            comment=f"{len(resume.experiences)} 段经历、{len(work_bullets)} 条工作要点，"
                    + ("项目颗粒度够" if len(work_bullets) >= 8 else "要点偏少，建议补充项目细节"),
        ),
        DimensionScore(
            name="量化成果",
            score=_clamp(30 + 65 * metric_ratio),
            comment=f"含量化数据的要点占 {metric_ratio:.0%}"
                    + ("，说服力良好" if metric_ratio >= 0.6 else "，多数条目缺数字，是最大短板"),
        ),
        DimensionScore(
            name="表达结构",
            score=_clamp(88 - 45 * weak_ratio - 6 * (1 if weak else 0)),
            comment=("「负责/参与」类弱动词 " + str(len(weak)) + " 处，建议换成主导/搭建/重构")
            if weak else "动词有力，句式统一",
        ),
        DimensionScore(
            name="岗位贴合",
            score=_clamp(36 + 58 * (0.65 * skill_rate + 0.35 * metric_ratio)),
            comment="与 JD 的核心场景" + ("高度重叠" if score >= 75 else "存在明显缺口，需要重排重点"),
        ),
    ]

    reqs: list[RequirementMatch] = []
    for req in nlp.split_requirements(jd, limit=7):
        req_kw = nlp.extract_keywords(req, top=6)
        hit = [k for k in req_kw if k.lower() in corpus]
        ratio = len(hit) / max(1, len(req_kw))
        evidence = _find_evidence(resume, hit)
        level = "strong" if ratio >= 0.65 and evidence else ("partial" if hit else "missing")
        reqs.append(
            RequirementMatch(
                requirement=req,
                evidence=evidence or "未体现",
                level=level,
                suggestion=(
                    "把「" + "、".join(hit[:2]) + "」直接写进要点的动作部分"
                    if hit
                    else "补一条同场景经历，或在项目中体现 " + (req_kw[0] if req_kw else "该能力")
                ),
            )
        )

    gaps: list[GapQuestion] = []
    # 追问只瞄准「工作/项目」条目：摘要和技能行不适合被追问量化数据
    work_bullets = [b for e in resume.experiences for b in e.bullets if b.original.strip()]
    work_bullets += [b for p in resume.projects for b in p.bullets if b.original.strip()]
    unquantified = [b for b in work_bullets if not nlp.has_metric(b.original) and len(b.original) > 8]
    unquantified.sort(key=lambda b: len(b.original), reverse=True)
    targets = (unquantified or work_bullets)[:4]
    if 0 < len(targets) < 3:  # 保证至少问 3 条，追问体验才成立
        targets = (targets + work_bullets)[:3]
    for i, (topic, ask) in enumerate(GAP_TOPICS[: len(targets)]):
        target = targets[i]
        gaps.append(
            GapQuestion(
                id=f"g{i + 1}",
                topic=topic,
                question=f"你写到「{_short(target.original, 22)}」——{ask}？",
                why="补上后这句就能变成「动作 + 量化结果」，直接进简历",
                bullet_id=target.id,
            )
        )

    templates = []
    try:
        templates = store.search(f"{jd[:600]}\n{' '.join(jd_keywords[:12])}", k=3)
    except Exception:  # noqa: BLE001
        templates = []

    verdict_pool = [
        "方向对得上，但简历还停留在「做过什么」，没有回答「做成了什么」。",
        "关键词基本齐了，表达密度不够：每三条要点只有一条带数字。",
        "经历与岗位有交集，但量化证据薄弱，面试官会连续追问数据。",
    ]
    rng = random.Random(len(resume_text) + (score * 7))
    return Diagnosis(
        match_score=score,
        verdict=rng.choice(verdict_pool) if score < 80 else "匹配度不错，补齐 3 处量化数据即可进入面试。",
        dimensions=dims,
        requirement_matches=reqs,
        missing_keywords=missing[:10],
        strengths=[
            f"关键词覆盖了 JD 的核心能力项：{'、'.join(matched[:3])}" if matched else "有真实的项目背景可挖",
            f"{len(resume.experiences)} 段经历时间线连续，具备可讲的故事线",
            "部分条目已带数字，具备改写基础",
        ],
        risks=[
            "「" + _short(bullets[0].original, 18) + "」缺少基线数据，容易被追问「提升多少」" if bullets else "项目描述缺少边界条件",
            "多条要点以「负责」开头，面试官难以判断你的实际贡献边界",
            "JD 要求的 " + ("、".join(missing[:2]) if missing else "部分能力") + " 在简历中没有对应证据",
        ],
        gap_questions=gaps,
        retrieved_templates=templates,
    )


def _find_evidence(resume: ResumeDoc, keywords: list[str]) -> str:
    best, best_hits = "", 0
    for b in resume.all_bullets():
        low = b.original.lower()
        hits = sum(1 for k in keywords if k.lower() in low)
        if hits > best_hits:
            best, best_hits = b.original, hits
    return _short(best, 46) if best_hits else ""


# --------------------------------------------------------------------------- #
# 2. 追问
# --------------------------------------------------------------------------- #
def next_gap_question(gap: GapQuestion, bullet_text: str) -> str:
    """问题在诊断阶段已组装好（含简历原句），这里只做去重保护。"""
    q = (gap.question or "").strip()
    if q:
        return q
    return f"关于「{_short(bullet_text, 20)}」，还缺一个具体数字，方便补充吗？"


# --------------------------------------------------------------------------- #
# 3. STAR 重写
# --------------------------------------------------------------------------- #
def _pick_action(text: str) -> str:
    # 长词优先，避免「协调研发」误命中「调研」这类中文子串碰撞
    for key, action in sorted(ACTION_LIBRARY.items(), key=lambda kv: -len(kv[0])):
        if key in text:
            return action
    return "梳理现状与瓶颈，重排优先级后分阶段推进"


def _pick_verb(text: str) -> str:
    if any(k in text for k in ("搭建", "从0", "从 0", "建设")):
        return "从 0 到 1 搭建"
    if any(k in text for k in ("优化", "提升", "改善", "降低")):
        return "重构"
    if any(k in text for k in ("分析", "研究", "评估")):
        return "量化分析"
    if any(k in text for k in ("策划", "组织", "活动")):
        return "主导"
    return "推动"


def _strip_weak(text: str) -> str:
    """把「负责/参与/协助」换成强动词，并保证开头只有一个动词。"""
    text = nlp.clean_bullet(text).rstrip("。；;")
    for weak, strong in WEAK_TO_STRONG.items():
        if text.startswith(weak):
            rest = text[len(weak):].lstrip("：: ，,")
            if rest:
                text = f"{strong}{rest}"
            break
    return text


def optimize_bullet(
    bullet_text: str,
    answer: str,
    context: str = "",
    metrics_hint: list[str] | None = None,
) -> tuple[str, StarBreakdown, list[str]]:
    """把一条原始要点 + 用户补充量化数据，组装成 STAR 句子。"""
    base = _strip_weak(bullet_text)
    base = re.sub(r"[，,。；;]+$", "", base)
    if not base.startswith(GOOD_VERBS):
        base = f"{_pick_verb(base)}{base}"
    action = _pick_action(bullet_text)

    answer = (answer or "").strip().rstrip("。；;")
    metrics = nlp.extract_metrics(answer) or (metrics_hint or [])
    if not metrics:
        metrics = nlp.extract_metrics(base)

    if answer:
        result = answer if len(answer) >= 6 else f"结果达到 {answer}"
        pieces = [base]
        if len(base) < 22:  # 原句太短时才补充方法，避免句子臃肿
            pieces.append(action)
        pieces.append(result)
        text = "，".join(pieces) + "。"
    else:
        tails = (
            "方法论沉淀为 SOP，在后续项目中复用",
            "方案沿用至 2 个后续项目",
            "相关流程成为团队标准动作",
        )
        tail = (f"核心指标在{'、'.join(metrics[:2])}上改善明显" if metrics
                else tails[sum(map(ord, bullet_text)) % len(tails)])
        text = f"{base}，{action}，{tail}。" if len(base) < 22 else f"{base}，{tail}。"
    if len(text) > 80:
        text = text[:76].rstrip("，、") + "。"

    star = StarBreakdown(
        situation=context or "业务处于扩张期，原有流程难以支撑规模增长",
        task=f"需要把「{_short(bullet_text, 18)}」这件事做出可衡量的结果",
        action=action,
        result=answer or ("；".join(metrics) if metrics else "待补充量化结果"),
    )
    return text, star, metrics


def rewrite(resume: ResumeDoc, answers: dict[str, str], jd: str = "") -> dict:
    """返回 {"bullets":[{id,optimized,star,metrics}], "summary":{...}, "skills":{...}}"""
    out_bullets = []

    def handle(b, context):
        answer = answers.get(b.id, "")
        if not b.original.strip():
            return
        text, star, metrics = optimize_bullet(b.original, answer, context, b.metrics)
        out_bullets.append(
            {"id": b.id, "optimized": text, "star": star.model_dump(), "metrics": metrics}
        )

    for exp in resume.experiences:
        ctx = f"{exp.company}{('·' + exp.role) if exp.role else ''}".strip("·")
        for b in exp.bullets:
            handle(b, ctx)
    for proj in resume.projects:
        for b in proj.bullets:
            handle(b, f"项目：{proj.name}")

    # 摘要：3 行内含年限/领域/最强战绩
    years = _estimate_years(resume)
    answer_metrics = nlp.extract_metrics(" ".join(answers.values()))
    pct = next((m for m in answer_metrics if ("%" in m or "倍" in m)), "")
    headline = resume.basics.headline or "目标岗位"
    jd_kw = nlp.extract_keywords(jd, top=4)
    result_clause = f"核心指标最高提升 {pct}" if pct else "推动核心指标持续改善"
    summary_text = (
        f"{years} 年{headline}经验，擅长{'、'.join(jd_kw[:3]) or '业务增长与项目落地'}；"
        f"有 {len(resume.experiences)} 段完整业务经历，{result_clause}；"
        "习惯用数据定位问题、用实验验证方案。"
    )[:150]

    skills_src = resume.skills.original or ", ".join(jd_kw[:6])
    skill_list = [s.strip() for s in re.split(r"[,，、|·]", skills_src) if s.strip()]
    ordered = [k for k in jd_kw if any(k.lower() in s.lower() for s in skill_list)] + skill_list
    seen: list[str] = []
    for s in ordered:
        if s and s not in seen:
            seen.append(s)
    skills_text = " · ".join(seen[:14])

    return {
        "summary": {
            "optimized": summary_text,
            "star": {
                "situation": "候选人背景与目标岗位的匹配点",
                "task": "用一句话说清能解决什么问题",
                "action": "领域 + 方法 + 代表项目",
                "result": pct or "待补充量化战绩",
            },
        },
        "skills": {"optimized": skills_text},
        "bullets": out_bullets,
    }


def _estimate_years(resume: ResumeDoc) -> int:
    """按时间线推断工作年限：最早年份 → 至今/最晚年份。"""
    from datetime import date

    years: list[int] = []
    ongoing = False
    for exp in resume.experiences:
        period = exp.period or ""
        years.extend(int(y) for y in re.findall(r"(?:19|20)\d{2}", period))
        if any(k in period for k in ("至今", "现在", "Present", "present")):
            ongoing = True
    if not years:
        return max(1, len(resume.experiences) * 2)
    end = date.today().year if ongoing else max(years)
    return max(1, min(25, end - min(years)))


def revision(resume: ResumeDoc, instruction: str) -> dict:
    """无 Key 模式下的「继续调整」：支持精简 / 加强量化 / 换动词三类高频诉求。"""
    brief = "精简" in instruction or "短" in instruction
    stronger = "量化" in instruction or "数据" in instruction or "结果" in instruction
    out = []
    for b in resume.all_bullets():
        if not b.optimized.strip():
            continue
        text = b.optimized
        if brief:
            text = re.split(r"[，,]", text)[0] + "。"
        if stronger and not nlp.has_metric(text):
            text = text.rstrip("。") + "，核心指标改善幅度待补充具体数字。"
        if text != b.optimized:
            out.append({"id": b.id, "optimized": text, "star": (b.star.model_dump() if b.star else None), "metrics": b.metrics})
    return {"summary": {}, "skills": {}, "bullets": out}


# --------------------------------------------------------------------------- #
# 4. 面试
# --------------------------------------------------------------------------- #
def interview_questions(resume: ResumeDoc, jd: str, template_hits: Iterable | None = None) -> list[InterviewQuestion]:
    bullets = [
        b for e in resume.experiences for b in e.bullets
    ] + [
        b for p in resume.projects for b in p.bullets
    ]
    bullets = [b for b in bullets if (b.optimized or b.original).strip()]
    if not bullets:
        bullets = [b for b in resume.all_bullets() if (b.optimized or b.original).strip()]
    bullets.sort(key=lambda b: len(b.optimized or b.original), reverse=True)
    jd_kw = nlp.extract_keywords(jd, top=8)
    exp = resume.experiences[0] if resume.experiences else None
    company = exp.company if exp else "上一家公司"
    role = resume.basics.headline or (exp.role if exp else "目标岗位")

    def txt(b) -> str:
        return (b.optimized or b.original).strip()

    q1 = txt(bullets[0]) if bullets else "你最有成就感的一个项目是什么？"
    q2 = txt(bullets[1]) if len(bullets) > 1 else q1
    all_metrics: list[str] = []
    for b in bullets[:6]:
        all_metrics.extend(nlp.extract_metrics(txt(b)))
    metric = next((m for m in all_metrics if any(c in m for c in "%％倍万亿")), "")

    qs = [
        InterviewQuestion(
            id="q1", index=1, kind="behavioral", difficulty="medium",
            question=f"你在{company}做的「{_short(q1, 24)}」，能完整讲一遍吗？我关心你个人的动作和最终结果。",
            intent="验证简历第一条的真实性与个人贡献边界",
            key_points=["项目背景与目标", "你个人的具体动作", "可验证的量化结果", "过程中的取舍"],
        ),
        InterviewQuestion(
            id="q2", index=2, kind="behavioral", difficulty="hard",
            question=f"你写到「{_short(q2, 22)}」，这个数字是怎么算出来的？基线是多少，有没有其他因素干扰？",
            intent="压力测试：核查数据口径与归因能力",
            key_points=["指标定义与口径", "基线值与计算方式", "归因与排除干扰", "如果没有你的参与会怎样"],
        ),
        InterviewQuestion(
            id="q3", index=3, kind="technical", difficulty="medium",
            question=f"如果让你从 0 再做一次这个方向（{('、'.join(jd_kw[:2]) or role)}），你会换掉哪个关键决策？为什么？",
            intent="考察方法论沉淀与技术判断，而不是经验复述",
            key_points=["复盘关键决策", "替代方案的取舍", "可迁移的方法论"],
        ),
        InterviewQuestion(
            id="q4", index=4, kind="situational", difficulty="medium",
            question=f"假设你入职后，业务方要求 4 周内上线一个{'、'.join(jd_kw[2:4]) or '核心功能'}，但研发资源只有一半，你会怎么排？",
            intent="考察优先级判断与跨部门推动力",
            key_points=["目标拆解与范围裁剪", "资源与风险评估", "向上沟通与对齐机制", "里程碑与验收标准"],
        ),
        InterviewQuestion(
            id="q5", index=5, kind="pressure", difficulty="hard",
            question=(
                f"简历里写着「{metric}」这样的提升，但据我所知同类业务很难做到。你怎么证明这不是口径美化？"
                if metric else
                "你的简历里有不少定性描述，如果我只给你 30 秒证明你适合这个岗位，你会说什么？"
            ),
            intent="抗压与诚信考察，看是否敢承认边界",
            key_points=["承认数据边界", "给出口径与证据", "区分个人贡献与团队贡献", "补充可验证的细节"],
        ),
    ]
    return qs


STAR_MARKERS: dict[str, tuple[str, ...]] = {
    "背景": ("当时", "背景", "业务", "接手", "负责", "日活", "规模", "现状", "团队"),
    "目标": ("目标", "要提升", "需要", "希望", "KPI", "要求", "为了"),
    "动作": ("我", "设计", "搭建", "推动", "主导", "做了", "拆分", "优化", "调研", "上线", "策略"),
    "结果": ("最终", "结果", "提升", "下降", "缩短", "增长", "降低", "从", "达到", "带来"),
    "反思": ("复盘", "如果重来", "反思", "沉淀", "学到", "下次"),
}


def _star_hits(answer: str) -> list[str]:
    return [k for k, kws in STAR_MARKERS.items() if any(w in answer for w in kws)]


def _covers(point: str, answer: str) -> bool:
    """把抽象考察点映射到可观测的表达要素，避免逐字匹配导致永远判缺失。"""
    p, a = point, answer
    if any(k in p for k in ("背景", "目标", "现状")):
        return any(w in a for w in ("当时", "背景", "业务", "目标是", "为了", "接手"))
    if any(k in p for k in ("动作", "贡献", "方法", "拆解", "执行")):
        return any(w in a for w in ("我", "设计", "搭建", "推动", "主导", "策略", "上线", "拆"))
    if any(k in p for k in ("量化", "数据", "结果", "指标", "口径", "基线", "证据")):
        return bool(nlp.extract_metrics(a)) or any(w in a for w in ("口径", "基线", "对比", "算出来"))
    if any(k in p for k in ("取舍", "反思", "复盘", "风险", "沟通", "归因")):
        return any(w in a for w in ("取舍", "权衡", "复盘", "风险", "优先", "放弃", "如果重来", "归因", "因为"))
    if any(k in p for k in ("个人", "团队")):
        return any(w in a for w in ("我", "团队", "协作", "配合"))
    # 兜底：考察点的 2-gram 命中率
    grams = [p[i : i + 2] for i in range(len(p) - 1)]
    hit = sum(1 for g in grams if g in a)
    return bool(grams) and hit / len(grams) >= 0.4


def feedback(question: InterviewQuestion, answer: str) -> AnswerFeedback:
    answer = (answer or "").strip()
    metrics = nlp.extract_metrics(answer)
    covered = [p for p in question.key_points if _covers(p, answer)]
    cover_rate = len(covered) / max(1, len(question.key_points))
    hits = _star_hits(answer)
    structure_hits = len(hits)
    fillers = sum(1 for f in FILLERS if f in answer)

    s_structure = _clamp(38 + structure_hits * 10 + (6 if metrics else 0), 20, 95)
    s_content = _clamp(34 + 30 * cover_rate + 6 * structure_hits + min(8, len(answer) / 40), 20, 96)
    s_data = _clamp(32 + min(56, 21 * len(metrics)) if answer else 20, 15, 96)
    s_expr = _clamp(46 + min(36, len(answer) / 5) - fillers * 6, 20, 94)

    if len(answer) < 12:
        total = _clamp(22 + len(answer), 10, 35)
    else:
        total = _clamp(0.26 * s_structure + 0.30 * s_content + 0.28 * s_data + 0.16 * s_expr, 10, 96)

    if total >= 85:
        verdict = "回答完整，STAR 清晰且有数据支撑，属于高分回答。"
    elif total >= 72:
        verdict = "结构基本成立，但结果与归因还差一层，容易被继续追问。"
    elif total >= 58:
        verdict = "讲清了做了什么，没讲清带来了什么；数字缺失让可信度打折。"
    else:
        verdict = "回答过于笼统，面试官无法判断你的真实贡献，建议按 STAR 重讲一遍。"

    improvements = []
    if not metrics:
        improvements.append("补一个可验证的数字：规模（用户/订单/预算）、幅度（%）、或周期（天）。")
    if structure_hits < 3:
        improvements.append("先交代背景与目标，再讲你的动作，最后落到结果，避免从头到尾平铺。")
    missing = [p for p in question.key_points if p not in covered]
    if missing:
        improvements.append("漏掉了考察点：" + "、".join(missing[:2]) + "。")
    if len(answer) < 80:
        improvements.append("回答偏短，建议补充「为什么这么做」的取舍，体现判断力。")
    if not improvements:
        improvements.append("可以再补一句复盘：如果重来一次会改哪个决策，体现成长性。")

    strengths = []
    if metrics:
        strengths.append("给出了具体数字（" + "、".join(metrics[:3]) + "），说服力强。")
    if structure_hits >= 3:
        strengths.append("叙述有先后顺序，面试官容易跟上。")
    if cover_rate >= 0.6:
        strengths.append("覆盖了本题的主要考察点。")
    if not strengths:
        strengths.append("态度坦诚，没有过度包装。")

    ref = (
        f"背景：{question.key_points[0] if question.key_points else '业务处于增长瓶颈期'}，"
        f"当时我负责的部分是……；"
        f"目标是……（给一个可衡量目标）；"
        f"我做了三件事：{'、'.join(question.key_points[1:3]) or '定位问题、拆解方案、推动落地'}；"
        f"最终结果是……（补一个数字），"
        f"这个过程让我沉淀了……，如果重来一次我会在……上更早介入。"
    )

    return AnswerFeedback(
        question_id=question.id,
        answer=answer,
        score=total,
        verdict=verdict,
        scores=[
            ScoreItem(name="结构(STAR)", score=s_structure),
            ScoreItem(name="内容深度", score=s_content),
            ScoreItem(name="数据支撑", score=s_data),
            ScoreItem(name="表达与逻辑", score=s_expr),
        ],
        strengths=strengths[:3],
        improvements=improvements[:3],
        missing_key_points=missing[:3],
        reference_answer=ref,
    )





def report(feedbacks: list[AnswerFeedback], questions: list[InterviewQuestion]) -> InterviewReport:
    if not feedbacks:
        return InterviewReport(overall=0, level="待提升", summary="还没有作答记录。", advice=[])
    overall = _clamp(sum(f.score for f in feedbacks) / len(feedbacks))
    dims: dict[str, list[int]] = {}
    for f in feedbacks:
        for s in f.scores:
            dims.setdefault(s.name, []).append(s.score)
    by_dim = [ScoreItem(name=k, score=_clamp(sum(v) / len(v))) for k, v in dims.items()]
    level = "优秀" if overall >= 85 else "良好" if overall >= 72 else "合格" if overall >= 60 else "待提升"
    weakest = min(by_dim, key=lambda d: d.score) if by_dim else None
    strongest = max(by_dim, key=lambda d: d.score) if by_dim else None
    summary = (
        f"共完成 {len(feedbacks)}/{len(questions)} 道题，平均分 {overall}，处于「{level}」区间。"
        f"最强项是{strongest.name}（{strongest.score}），最需要补的是{weakest.name}（{weakest.score}）。"
        "整体表达有事实基础，但量化证据的密度仍是主要扣分项。"
    )
    advice = [
        f"针对{weakest.name if weakest else '数据支撑'}做专项训练：每道题强制说出 2 个数字（规模 + 幅度）。",
        "用「背景 20% / 动作 50% / 结果 30%」的时长比例重录一遍答案，避免铺垫过长。",
        "准备 3 个可复用的项目故事（成功、失败、冲突各一个），覆盖 80% 行为面问题。",
        "面试前把简历里每个数字的口径、基线、归因都写成一句话备注，应对追问。",
    ]
    return InterviewReport(overall=overall, level=level, by_dimension=by_dim, summary=summary, advice=advice)


# --------------------------------------------------------------------------- #
# 5. 流式分片（打字机）
# --------------------------------------------------------------------------- #
def chunk_text(text: str, size: int = 3) -> Iterable[str]:
    for i in range(0, len(text), size):
        yield text[i : i + size]


def stream_delay() -> float:
    return max(0.0, settings.mock_delay)
