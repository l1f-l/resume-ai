"""PDF 解析：pdfplumber 为主，PyPDF2 兜底；再把纯文本结构化。"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from ..config import settings
from ..schemas import Basics, Bullet, Education, Experience, ProjectItem, ResumeDoc
from . import nlp


class PDFParseError(RuntimeError):
    pass


@dataclass
class ParsedPDF:
    text: str = ""
    pages: int = 0
    chars: int = 0
    method: str = ""
    warnings: list[str] = field(default_factory=list)
    scanned: bool = False          # 是否判定为扫描件
    ocr_engine: str = ""           # 实际使用的 OCR 引擎
    ocr_renderer: str = ""         # 实际使用的渲染器

    @property
    def ok(self) -> bool:
        return self.chars >= 50


def _should_merge(prev: str, nxt: str) -> bool:
    """判断是否是 PDF 硬换行导致的断句。宁可少合并，也不能把标题和条目粘连。"""
    if not prev or not nxt:
        return False
    if nlp.BULLET_PREFIX_RE.match(nxt) or nlp.BULLET_PREFIX_RE.match(prev):
        return False
    if "|" in prev or "|" in nxt or "｜" in prev:
        return False
    if nlp.PERIOD_RE.search(prev) or nlp.PERIOD_RE.search(nxt):
        return False
    if prev[-1] in "。；;：:！？!?）)":
        return False
    if len(prev.strip()) < 30:
        return False
    if len(nxt.strip()) <= 14 and not re.search(r"[，。、；,]", nxt):
        return False  # 短行大概率是小标题 / 公司名，不合并
    return bool(re.search(r"[\u4e00-\u9fa5，、]$", prev)) and bool(re.match(r"^[\u4e00-\u9fa5]", nxt))


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\xa0", " ").replace("\u200b", "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    # 合并被 PDF 硬换行拆断的中文长句（严格条件，避免把标题和条目粘在一起）
    merged: list[str] = []
    for ln in lines:
        prev = merged[-1] if merged else ""
        if _should_merge(prev, ln):
            merged[-1] = prev + ln
        else:
            merged.append(ln)
    out = "\n".join(merged)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _extract_text_layer(data: bytes) -> tuple[str, int, str, list[str]]:
    """尝试 PDF 文本层：pdfplumber 为主，PyPDF2 兜底。"""
    warnings: list[str] = []
    text, pages, method = "", 0, ""

    try:
        import pdfplumber  # noqa: PLC0415

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = len(pdf.pages)
            chunks = []
            for page in pdf.pages:
                chunks.append(page.extract_text(x_tolerance=1.5, y_tolerance=3) or "")
            text = "\n".join(chunks)
        method = "pdfplumber"
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"pdfplumber 解析失败：{exc}")

    if len(nlp.normalize(text)) < 50:
        try:
            from PyPDF2 import PdfReader  # noqa: PLC0415

            reader = PdfReader(io.BytesIO(data))
            pages = pages or len(reader.pages)
            fallback = "\n".join((p.extract_text() or "") for p in reader.pages)
            if len(nlp.normalize(fallback)) > len(nlp.normalize(text)):
                text = fallback
                method = f"{method}+PyPDF2" if method else "PyPDF2"
                warnings.append("已回退到 PyPDF2 提取")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"PyPDF2 解析失败：{exc}")

    return text, pages, method, warnings


def parse_pdf(data: bytes) -> ParsedPDF:
    """PDF → 文本。文本层过少时判定为扫描件并走 OCR。"""
    if not data:
        raise PDFParseError("文件为空")
    if not data[:5].startswith(b"%PDF"):
        raise PDFParseError("不是有效的 PDF 文件（缺少 %PDF 文件头）")

    text, pages, method, warnings = _extract_text_layer(data)
    cleaned = _clean(text)
    scanned = len(nlp.normalize(cleaned)) < settings.ocr_min_chars
    ocr_engine = ocr_renderer = ""

    if scanned:
        warnings.append(
            f"文本层仅 {len(nlp.normalize(cleaned))} 个字符（阈值 {settings.ocr_min_chars}），判定为扫描件，启动 OCR"
        )
        try:
            from .ocr import OCRError, ocr_pdf  # noqa: PLC0415

            result = ocr_pdf(data)
            cleaned = _clean(result.text)
            method = f"{method or 'pdf'}+ocr:{result.engine}"
            ocr_engine, ocr_renderer = result.engine, result.renderer
            pages = pages or result.pages
            warnings.extend(result.warnings)
            warnings.append(f"OCR 完成：{result.engine}（渲染 {result.renderer}，{result.pages} 页）")
        except OCRError as exc:
            raise PDFParseError(
                "这份 PDF 没有可提取的文字层，判定为扫描件/图片型简历，"
                f"OCR 也未能识别：{exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise PDFParseError(f"扫描件 OCR 失败：{exc}") from exc

    result = ParsedPDF(
        text=cleaned,
        pages=pages,
        chars=len(cleaned),
        method=method or "unknown",
        warnings=warnings,
        scanned=scanned,
        ocr_engine=ocr_engine,
        ocr_renderer=ocr_renderer,
    )
    if not result.ok:
        if scanned:
            raise PDFParseError(
                "这份简历疑似扫描件，OCR 后仍未识别出足够文字（少于 50 字）。"
                "请确认扫描清晰、方向正确，或上传可复制文字的 PDF。"
            )
        raise PDFParseError(
            "未能从 PDF 中提取到有效文字，可能是扫描件或纯图片简历，请上传可复制文字的 PDF"
        )
    return result


# --------------------------------------------------------------------------- #
# 结构化
# --------------------------------------------------------------------------- #
def _basics_from_lines(lines: list[str], full_text: str) -> Basics:
    basics = Basics()
    email = nlp.EMAIL_RE.search(full_text)
    phone = nlp.PHONE_RE.search(full_text)
    if email:
        basics.email = email.group(0)
    if phone:
        basics.phone = phone.group(0)
    basics.links = [m.group(0) for m in nlp.URL_RE.finditer(full_text)][:3]

    for line in lines[:4]:
        if nlp.EMAIL_RE.search(line) or nlp.PHONE_RE.search(line):
            continue
        parts = [p for p in re.split(r"[|｜·•/　]{1,2}", line) if p.strip()]
        if parts:
            cand = parts[0].strip()
            if 1 < len(cand) <= 8 and not nlp.has_metric(cand):
                basics.name = cand
            for p in parts[1:]:
                if any(k in p for k in ("工程师", "经理", "专家", "总监", "主管", "运营", "产品", "开发", "分析")):
                    basics.headline = basics.headline or p.strip()
            break
    if not basics.headline:
        for line in lines[:6]:
            if any(k in line for k in ("求职意向", "目标岗位", "应聘")):
                basics.headline = re.sub(r"^.*?(?:求职意向|目标岗位|应聘)[:：]?", "", line).strip()
                break
    m = re.search(r"(北京|上海|深圳|广州|杭州|成都|南京|武汉|西安|苏州|长沙|重庆|厦门|天津|合肥)", full_text)
    if m:
        basics.location = m.group(1)
    return basics


def _split_heading(line: str) -> tuple[str, str, str]:
    """把「字节跳动 | 高级产品经理 2021.03-2023.06」拆成 (公司, 职位, 时间)。"""
    period = ""
    m = nlp.PERIOD_RE.search(line)
    if m:
        period = f"{m.group(1)} - {m.group(2)}".replace(" ", "")
        line = (line[: m.start()] + " " + line[m.end() :]).strip()
    parts = [p.strip(" -|｜·\t") for p in re.split(r"[|｜·\t]| {2,}", line) if p.strip(" -|｜·\t")]
    if len(parts) >= 2:
        role_hint = ("经理", "工程师", "专家", "总监", "主管", "专员", "开发", "运营", "产品", "分析", "设计", "顾问", "实习")
        if any(k in parts[0] for k in role_hint) and not any(k in parts[1] for k in role_hint):
            parts[0], parts[1] = parts[1], parts[0]
        return parts[0][:40], parts[1][:40], period
    seg = parts[0] if parts else line
    return seg[:40], "", period


def structure_heuristic(text: str) -> ResumeDoc:
    sections = nlp.split_sections(text)
    header_lines = sections.get("header", [])
    doc = ResumeDoc(basics=_basics_from_lines(header_lines, text))

    doc.summary = Bullet(id="summary", original=" ".join(sections.get("summary", []))[:400])
    doc.skills = Bullet(id="skills", original=", ".join(sections.get("skills", []))[:400])

    # 工作经历
    seq = 0
    for line in sections.get("experience", []):
        stripped = nlp.clean_bullet(line)
        is_heading = (
            bool(nlp.PERIOD_RE.search(line))
            or (
                not nlp.BULLET_PREFIX_RE.match(line)
                and len(stripped) <= 34
                and any(k in stripped for k in ("公司", "集团", "科技", "有限", "Inc", "Ltd", "字节", "腾讯", "阿里", "美团"))
            )
        )
        if is_heading or not doc.experiences:
            seq += 1
            company, role, period = _split_heading(stripped)
            doc.experiences.append(
                Experience(id=f"exp{seq}", company=company, role=role, period=period, bullets=[])
            )
        else:
            doc.experiences[-1].bullets.append(Bullet(id="tmp", original=stripped[:300]))

    # 项目
    pseq = 0
    for line in sections.get("projects", []):
        stripped = nlp.clean_bullet(line)
        if not doc.projects or (not nlp.BULLET_PREFIX_RE.match(line) and len(stripped) <= 30):
            pseq += 1
            name, role, period = _split_heading(stripped)
            doc.projects.append(ProjectItem(id=f"proj{pseq}", name=name, role=role, period=period))
        else:
            doc.projects[-1].bullets.append(Bullet(id="tmp", original=stripped[:300]))

    # 教育
    for i, line in enumerate(sections.get("education", [])[:4], start=1):
        m = nlp.PERIOD_RE.search(line)
        period = f"{m.group(1)} - {m.group(2)}" if m else ""
        probe = nlp.PERIOD_RE.sub("", line)
        parts = [p for p in re.split(r"[|｜·\s]{1,2}", probe) if p.strip()]
        school = (parts[0] if parts else probe)[:40]
        degree = next((p for p in parts if any(k in p for k in ("本科", "硕士", "博士", "专科", "学士"))), "")
        major = next((p for p in parts if p not in (school, degree) and "专业" in p), "")
        if not major:
            major = next((p for p in parts[1:] if p not in (school, degree) and "大学" not in p), "")
        doc.education.append(
            Education(id=f"edu{i}", school=school, degree=degree, major=major[:40],
                      period=period, detail="")
        )

    doc.extras = sections.get("extras", [])[:8]
    _assign_ids(doc)
    return doc


def _assign_ids(doc: ResumeDoc) -> None:
    """全局唯一 bullet id，前端对比/重写回填都靠它。"""
    n = 0
    for exp in doc.experiences:
        for b in exp.bullets:
            n += 1
            b.id = f"b{n}"
            b.metrics = nlp.extract_metrics(b.original)
    for proj in doc.projects:
        for b in proj.bullets:
            n += 1
            b.id = f"b{n}"
            b.metrics = nlp.extract_metrics(b.original)
    doc.summary.id, doc.skills.id = "summary", "skills"


async def structure_resume(text: str, llm) -> tuple[ResumeDoc, str]:
    """优先用模型结构化，失败则用启发式（保证任何情况下都有可预览的结构）。"""
    fallback = structure_heuristic(text)
    if llm.is_mock:
        return fallback, "heuristic"
    from ..prompts import STRUCTURE_RESUME, SYSTEM_RESUME_ARCHITECT  # noqa: PLC0415

    try:
        data = await llm.complete_json(
            [
                {"role": "system", "content": SYSTEM_RESUME_ARCHITECT},
                {"role": "user", "content": STRUCTURE_RESUME.format(resume=text[:12000])},
            ],
            temperature=0.1,
        )
        doc = _doc_from_llm(data, fallback)
        return doc, "llm"
    except Exception:  # noqa: BLE001
        return fallback, "heuristic"


def _doc_from_llm(data: dict, fallback: ResumeDoc) -> ResumeDoc:
    b = data.get("basics") or {}
    doc = ResumeDoc(
        basics=Basics(
            name=str(b.get("name") or "")[:30],
            headline=str(b.get("headline") or "")[:60],
            phone=str(b.get("phone") or "") or fallback.basics.phone,
            email=str(b.get("email") or "") or fallback.basics.email,
            location=str(b.get("location") or "") or fallback.basics.location,
            links=[str(x)[:80] for x in (b.get("links") or [])][:3],
        ),
        summary=Bullet(id="summary", original=str(data.get("summary") or "")[:400]),
        skills=Bullet(id="skills", original=str(data.get("skills") or "")[:400]),
        extras=[str(x)[:120] for x in (data.get("extras") or [])][:8],
    )
    for i, exp in enumerate((data.get("experiences") or [])[:8], start=1):
        doc.experiences.append(
            Experience(
                id=f"exp{i}",
                company=str(exp.get("company") or "")[:60],
                role=str(exp.get("role") or "")[:60],
                period=str(exp.get("period") or "")[:40],
                location=str(exp.get("location") or "")[:30],
                bullets=[Bullet(id="tmp", original=str(x)[:300]) for x in (exp.get("bullets") or [])][:10],
            )
        )
    for i, proj in enumerate((data.get("projects") or [])[:6], start=1):
        doc.projects.append(
            ProjectItem(
                id=f"proj{i}",
                name=str(proj.get("name") or "")[:60],
                role=str(proj.get("role") or "")[:40],
                period=str(proj.get("period") or "")[:40],
                bullets=[Bullet(id="tmp", original=str(x)[:300]) for x in (proj.get("bullets") or [])][:8],
            )
        )
    for i, edu in enumerate((data.get("education") or [])[:4], start=1):
        doc.education.append(
            Education(
                id=f"edu{i}",
                school=str(edu.get("school") or "")[:60],
                degree=str(edu.get("degree") or "")[:30],
                major=str(edu.get("major") or "")[:40],
                period=str(edu.get("period") or "")[:40],
                detail=str(edu.get("detail") or "")[:120],
            )
        )
    if not doc.experiences:
        doc.experiences = fallback.experiences
    if not doc.basics.name:
        doc.basics.name = fallback.basics.name
    _assign_ids(doc)
    return doc
