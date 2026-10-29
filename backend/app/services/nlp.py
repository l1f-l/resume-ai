"""轻量 NLP 工具：中文分词不必上重模型，用词表 + 正则足够支撑演示引擎与 RAG 检索。"""
from __future__ import annotations

import re

# 覆盖技术 / 产品 / 运营 / 数据 / 财务 / 管理几类高频 JD 关键词
SKILL_LEXICON: tuple[str, ...] = (
    # 技术
    "Python", "Java", "Go", "TypeScript", "JavaScript", "React", "Vue", "Next.js", "Node.js",
    "FastAPI", "Django", "Spring Boot", "MySQL", "PostgreSQL", "Redis", "Kafka", "Docker",
    "Kubernetes", "K8s", "Linux", "Git", "CI/CD", "微服务", "分布式", "高并发", "中间件",
    "机器学习", "深度学习", "PyTorch", "TensorFlow", "大模型", "LLM", "RAG", "Agent",
    "Prompt", "推荐系统", "NLP", "数据挖掘", "特征工程", "A/B 测试", "A/B测试",
    # 数据 / 分析
    "SQL", "Hive", "Spark", "Flink", "Tableau", "Power BI", "Excel", "数据建模", "数据看板",
    "指标体系", "埋点", "用户画像", "归因分析", "漏斗分析", "AB 实验", "统计分析",
    # 产品 / 运营
    "需求分析", "PRD", "用户调研", "竞品分析", "产品设计", "用户体验", "原型", "Figma",
    "用户增长", "私域", "社群运营", "内容运营", "活动运营", "商业化", "投放", "SEO", "SEM",
    "GMV", "ROI", "DAU", "MAU", "留存率", "转化率", "复购", "客单价", "生命周期",
    "项目管理", "PMP", "敏捷", "Scrum", "跨部门协作", "利益相关方",
    # 通用商业
    "财务分析", "预算", "成本控制", "CPA", "ACCA", "审计", "风控", "合规", "供应链",
    "商务谈判", "大客户", "SOP", "OKR", "KPI", "英语", "雅思", "TOEFL",
)

WEAK_PREFIXES = ("负责", "参与", "协助", "配合", "帮助", "从事", "完成")
STRONG_VERBS = (
    "主导", "搭建", "重构", "推动", "落地", "牵头", "设计", "优化", "量化", "整合",
    "拆解", "复盘", "沉淀", "驱动", "交付", "提升", "降低", "缩短", "拓展",
)

METRIC_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:%|％|倍|万|亿|人|天|小时|分钟|秒|个|项|次|元|K|W|QPS|ms))"
    r"|(\d{2,}[,]?\d*)"
    r"|(翻[一两三四五几\d]+倍)"
    r"|(从\s*\d+[^，。；]{0,6}?到\s*\d+)"
)

BULLET_PREFIX_RE = re.compile(r"^[\s\-•·●▪◦*>]+")
SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "summary": ("个人简介", "自我评价", "个人总结", "职业概述", "summary", "profile", "about"),
    "skills": ("专业技能", "技能", "技术栈", "技能清单", "skills", "expertise"),
    "experience": ("工作经历", "工作经验", "职业经历", "实习经历", "experience", "employment"),
    "projects": ("项目经历", "项目经验", "核心项目", "projects", "project experience"),
    "education": ("教育背景", "教育经历", "学历", "education"),
    "extras": ("证书", "荣誉", "奖项", "获奖", "语言能力", "certificates", "awards"),
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"(?:\+?86[-\s]?)?1[3-9]\d{9}")
URL_RE = re.compile(r"(?:https?://|www\.)\S+|github\.com/\S+|linkedin\.com/\S+")
PERIOD_RE = re.compile(
    r"((?:19|20)\d{2}\s*[./年-]\s*(?:1[0-2]|0?[1-9])?)\s*[-–—~至]+\s*"
    r"((?:(?:19|20)\d{2}\s*[./年-]\s*(?:1[0-2]|0?[1-9])?)|至今|现在|Present)",
    re.I,
)


def normalize(text: str) -> str:
    return re.sub(r"[ \t\u3000]+", " ", text.replace("\r\n", "\n")).strip()


def clean_bullet(line: str) -> str:
    return BULLET_PREFIX_RE.sub("", line).strip(" \t;；")


def extract_metrics(text: str) -> list[str]:
    out: list[str] = []
    for m in METRIC_RE.finditer(text or ""):
        token = next((g for g in m.groups() if g), "")
        token = token.strip()
        if token and token not in out:
            out.append(token)
    return out


def has_metric(text: str) -> bool:
    return bool(extract_metrics(text))


def extract_keywords(text: str, top: int = 18) -> list[str]:
    """词表命中 + 英文标识符，按出现频次排序。"""
    text = text or ""
    lowered = text.lower()
    hits: dict[str, int] = {}
    for kw in SKILL_LEXICON:
        n = lowered.count(kw.lower())
        if n:
            hits[kw] = n
    for m in re.finditer(r"\b[A-Za-z][A-Za-z0-9.+#/-]{1,20}\b", text):
        tok = m.group(0)
        if tok.lower() in {"and", "the", "for", "with", "from", "your", "our", "you", "are"}:
            continue
        hits.setdefault(tok, 1)
    ranked = sorted(hits.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    return [k for k, _ in ranked[:top]]


def split_requirements(jd: str, limit: int = 8) -> list[str]:
    """把 JD 拆成可逐条匹配的要求句。"""
    raw = re.split(r"[\n。；;•·●▪]|(?:\d+[.)、])", jd or "")
    cues = ("负责", "要求", "熟悉", "精通", "具备", "了解", "经验", "能力", "优先", "熟练",
            "掌握", "本科", "年以上", "背景", "素养")
    headings = {"岗位职责", "工作职责", "职位描述", "任职要求", "岗位要求", "任职资格",
                "职责描述", "工作内容", "加分项", "我们希望你", "你将负责"}
    out: list[str] = []
    for seg in raw:
        s = clean_bullet(seg).strip(" ，,、")
        if s.rstrip("：: ") in headings or len(s) < 10:
            continue
        if any(c in s for c in cues):
            out.append(s[:90])
        if len(out) >= limit:
            break
    if not out:  # JD 很短时退化为按句切
        out = [s.strip()[:90] for s in re.split(r"[。\n]", jd or "") if len(s.strip()) > 6][:limit]
    return out


def split_sections(text: str) -> dict[str, list[str]]:
    """按常见简历小标题切段，返回 {section: [lines]}。"""
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        probe = re.sub(r"[:：|·\s]", "", line).lower()
        matched = None
        for key, aliases in SECTION_ALIASES.items():
            if any(probe == a.lower().replace(" ", "") or probe.startswith(a.lower().replace(" ", ""))
                   for a in aliases) and len(probe) <= len(max(aliases, key=len)) + 6:
                matched = key
                break
        if matched and len(probe) <= 18:
            current = matched
            sections.setdefault(current, [])
            rest = re.sub(r"^[^:：]*[:：]", "", line).strip()
            if rest and rest != line:
                sections[current].append(rest)
            continue
        sections.setdefault(current, []).append(line)
    return sections


def is_weak_phrase(text: str) -> bool:
    head = clean_bullet(text)[:4]
    return any(head.startswith(w) for w in WEAK_PREFIXES)


def split_qa_pairs(answers: dict[str, str]) -> str:
    if not answers:
        return "（候选人未提供额外数据）"
    return "\n".join(f"Q: {q}\nA: {a}" for q, a in answers.items() if a.strip())
