"""导出：单文件 HTML（离线可用、可直接打印为 PDF）与 reportlab 原生 PDF。"""
from __future__ import annotations

import html
import io
import re
from datetime import datetime
from pathlib import Path

from ..schemas import Bullet, ResumeDoc

PALETTE = {
    "ink": "#111827",
    "sub": "#4b5563",
    "line": "#e5e7eb",
    "accent": "#0f766e",
    "red": "#b91c1c",
    "green": "#047857",
}


# --------------------------------------------------------------------------- #
# 通用：把结构化简历摊平成渲染块
# --------------------------------------------------------------------------- #
def _bullet_text(b: Bullet, variant: str) -> str:
    return b.optimized if (variant != "original" and b.optimized) else b.original


def contact_line(resume: ResumeDoc) -> str:
    b = resume.basics
    parts = [p for p in (b.phone, b.email, b.location, *b.links) if p]
    return " · ".join(parts)


# --------------------------------------------------------------------------- #
# 1) 单文件 HTML
# --------------------------------------------------------------------------- #
def render_html(resume: ResumeDoc, variant: str = "optimized", title: str | None = None) -> str:
    e = html.escape
    b = resume.basics
    name = e(b.name or "候选人")
    headline = e(b.headline or "")
    contact = e(contact_line(resume))
    diff = variant == "diff"

    def bullet_html(bul: Bullet) -> str:
        original = e(bul.original.strip())
        optimized = e((bul.optimized or bul.original).strip())
        if not diff:
            return f'<li>{e(_bullet_text(bul, variant))}</li>'
        if not bul.optimized or bul.optimized.strip() == bul.original.strip():
            return f'<li class="same">{original}</li>'
        return (
            f'<li class="diff"><span class="del">{original}</span>'
            f'<span class="ins">{optimized}</span></li>'
        )

    def section(title_: str, inner: str) -> str:
        return f'<section><h2>{e(title_)}</h2>{inner}</section>' if inner.strip() else ""

    summary = ""
    if resume.summary.optimized or resume.summary.original:
        summary = section(
            "个人简介",
            f'<p class="summary">{e(_bullet_text(resume.summary, variant))}</p>',
        )

    skills_text = _bullet_text(resume.skills, variant)
    skills = ""
    if skills_text:
        chips = [s.strip() for s in re.split(r"[,，、·|]", skills_text) if s.strip()][:24]
        skills = section("专业技能", '<p class="skills">' + "".join(f"<span>{e(c)}</span>" for c in chips) + "</p>")

    exp_html = ""
    for exp in resume.experiences:
        head = "".join(
            x for x in [
                f'<span class="org">{e(exp.company)}</span>' if exp.company else "",
                f'<span class="role">{e(exp.role)}</span>' if exp.role else "",
            ] if x
        )
        period = f'<span class="period">{e(exp.period)}</span>' if exp.period else ""
        items = "".join(bullet_html(x) for x in exp.bullets if x.original.strip())
        exp_html += f'<div class="item"><div class="item-head"><div class="head-left">{head}</div>{period}</div><ul>{items}</ul></div>'
    exp_section = section("工作经历", exp_html)

    proj_html = ""
    for p in resume.projects:
        head = f'<span class="org">{e(p.name)}</span>' + (f'<span class="role">{e(p.role)}</span>' if p.role else "")
        period = f'<span class="period">{e(p.period)}</span>' if p.period else ""
        items = "".join(bullet_html(x) for x in p.bullets if x.original.strip())
        proj_html += f'<div class="item"><div class="item-head"><div class="head-left">{head}</div>{period}</div><ul>{items}</ul></div>'
    proj_section = section("项目经历", proj_html)

    edu_html = ""
    for edu in resume.education:
        right = " · ".join(x for x in (edu.degree, edu.period) if x)
        edu_html += (
            f'<div class="item edu"><div class="item-head"><div class="head-left"><span class="org">{e(edu.school)}</span></div>'
            f'<span class="period">{e(right)}</span></div>'
            f'<div class="edu-major">{e(edu.major)} {e(edu.detail)}</div></div>'
        )
    edu_section = section("教育背景", edu_html)

    extras = section("证书 / 荣誉", "<ul>" + "".join(f"<li>{e(x)}</li>" for x in resume.extras) + "</ul>") if resume.extras else ""

    badge = {
        "optimized": '<span class="badge ok">STAR 优化版</span>',
        "diff": '<span class="badge diff">改前 / 改后对比版</span>',
        "original": '<span class="badge">原始版</span>',
    }.get(variant, "")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{e(title or (b.name + ' 的简历'))}</title>
<style>
  :root {{
    --ink: {PALETTE['ink']}; --sub: {PALETTE['sub']}; --line: {PALETTE['line']};
    --accent: {PALETTE['accent']}; --red: {PALETTE['red']}; --green: {PALETTE['green']};
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: #f3f4f6; }}
  body {{
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Hiragino Sans GB",
                 "Source Han Sans SC", "Noto Sans CJK SC", Arial, sans-serif;
    color: var(--ink); line-height: 1.62; font-size: 13.5px;
  }}
  .page {{
    width: 210mm; min-height: 297mm; margin: 24px auto; background: #fff;
    padding: 16mm 15mm 14mm; box-shadow: 0 6px 28px rgba(15,23,42,.10);
  }}
  /* 嵌在 iframe 里预览时按容器宽度自适应，打印仍保持 A4 */
  @media screen and (max-width: 860px) {{
    .page {{ width: min(210mm, calc(100% - 20px)); padding: 12mm 10mm; margin: 10px auto; }}
  }}
  header {{ border-bottom: 2px solid var(--ink); padding-bottom: 10px; margin-bottom: 14px; }}
  .name-row {{ display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }}
  h1 {{ font-size: 27px; margin: 0; letter-spacing: .5px; font-weight: 700; }}
  .headline {{ color: var(--accent); font-weight: 600; font-size: 14px; }}
  .contact {{ color: var(--sub); font-size: 12px; margin-top: 6px; word-break: break-all; }}
  .badge {{
    float: right; font-size: 11px; border: 1px solid var(--line); color: var(--sub);
    padding: 2px 8px; border-radius: 999px; background: #f9fafb;
  }}
  .badge.ok {{ color: var(--green); border-color: #a7f3d0; background: #ecfdf5; }}
  .badge.diff {{ color: #92400e; border-color: #fde68a; background: #fffbeb; }}
  section {{ margin-bottom: 15px; }}
  h2 {{
    font-size: 12px; letter-spacing: 2px; text-transform: uppercase; color: var(--accent);
    margin: 0 0 7px; padding-bottom: 4px; border-bottom: 1px solid var(--line); font-weight: 700;
  }}
  .summary {{ margin: 0; color: #1f2937; }}
  .skills {{ margin: 0; display: flex; flex-wrap: wrap; gap: 6px; }}
  .skills span {{
    background: #f1f5f9; border: 1px solid var(--line); border-radius: 4px;
    padding: 1px 7px; font-size: 12px; color: #334155;
  }}
  .item {{ margin-bottom: 11px; page-break-inside: avoid; }}
  .item-head {{ display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }}
  .head-left {{ display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; min-width: 0; }}
  .org {{ font-weight: 600; }}
  .role {{ color: var(--sub); font-size: 12.5px; }}
  .period {{ color: var(--sub); font-size: 12px; white-space: nowrap; }}
  ul {{ margin: 4px 0 0; padding-left: 17px; }}
  li {{ margin: 2px 0; }}
  li::marker {{ color: #9ca3af; }}
  li.diff {{ list-style: none; margin-left: -14px; }}
  li.diff .del {{ color: var(--red); text-decoration: line-through; opacity: .75; display: block; }}
  li.diff .ins {{ color: var(--green); display: block; }}
  li.diff .ins::before {{ content: "→ "; color: #9ca3af; text-decoration: none; }}
  .edu-major {{ color: var(--sub); font-size: 12.5px; }}
  footer {{ margin-top: 18px; padding-top: 8px; border-top: 1px solid var(--line);
            color: #9ca3af; font-size: 10.5px; display: flex; justify-content: space-between; }}
  @page {{ size: A4; margin: 0; }}
  @media print {{
    html, body {{ background: #fff; }}
    .page {{ box-shadow: none; margin: 0; width: auto; min-height: auto; padding: 14mm 14mm; }}
    .badge {{ display: none; }}
  }}
</style>
</head>
<body>
  <div class="page">
    <header>
      {badge}
      <div class="name-row">
        <h1>{name}</h1>
        {f'<span class="headline">{headline}</span>' if headline else ''}
      </div>
      <div class="contact">{contact}</div>
    </header>
    {summary}
    {skills}
    {exp_section}
    {proj_section}
    {edu_section}
    {extras}
    <footer>
      <span>ResumePilot · 由 AI 优化生成</span>
      <span>{datetime.now().strftime('%Y-%m-%d')}</span>
    </footer>
  </div>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# 2) PDF（reportlab）
# --------------------------------------------------------------------------- #
#: 优先嵌入系统真字体（文本可复制/可检索，字重也正常），找不到再退回 CID 字体
FONT_CANDIDATES: tuple[tuple[str, str, int, str | None], ...] = (
    ("MicrosoftYaHei", r"C:/Windows/Fonts/msyh.ttc", 0, r"C:/Windows/Fonts/msyhbd.ttc"),
    ("SimHei", r"C:/Windows/Fonts/simhei.ttf", 0, None),
    ("PingFang", "/System/Library/Fonts/PingFang.ttc", 0, None),
    ("NotoSansCJK", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0,
     "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    ("NotoSansSC", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 0, None),
    ("WQYZenHei", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0, None),
    ("Deng", r"C:/Windows/Fonts/Deng.ttf", 0, r"C:/Windows/Fonts/Dengb.ttf"),
)

_FONT_CACHE: tuple[str, str] | None = None


def _register_cjk() -> tuple[str, str]:
    """返回 (正文字体, 粗体字体)。"""
    global _FONT_CACHE
    if _FONT_CACHE:
        return _FONT_CACHE

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for name, path, index, bold_path in FONT_CANDIDATES:
        if not Path(path).exists():
            continue
        try:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=index))
            bold = name
            if bold_path and Path(bold_path).exists():
                bname = f"{name}-Bold"
                if bname not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(bname, bold_path, subfontIndex=index))
                bold = bname
            _FONT_CACHE = (name, bold)
            return _FONT_CACHE
        except Exception:  # noqa: BLE001 - 字体损坏/权限问题就换下一个
            continue

    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    try:
        pdfmetrics.getFont("STSong-Light")
    except KeyError:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    _FONT_CACHE = ("STSong-Light", "STSong-Light")
    return _FONT_CACHE


def _tokens(text: str) -> list[str]:
    """中文按字断行，英文/数字按词断行。"""
    return re.findall(r"[A-Za-z0-9@._%+\-/]+|\s+|.", text)


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    lines: list[str] = []
    line = ""
    for tok in _tokens(text):
        candidate = line + tok
        if stringWidth(candidate, font, size) <= width or not line:
            line = candidate
        else:
            lines.append(line.rstrip())
            line = tok.lstrip()
    if line.strip():
        lines.append(line.rstrip())
    # 标点不孤行：把行首标点回贴到上一行
    fixed: list[str] = []
    for ln in lines:
        if fixed and ln and ln[0] in "，。；：、）」』】!?！？":
            fixed[-1] += ln[0]
            ln = ln[1:]
        if ln:
            fixed.append(ln)
    return fixed or [""]


def render_pdf(resume: ResumeDoc, variant: str = "optimized") -> bytes:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    font, bold = _register_cjk()
    buf = io.BytesIO()
    W, H = A4
    left, right, top, bottom = 46, 46, 48, 46
    usable = W - left - right
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"{(resume.basics.name or '候选人')} 的简历")
    c.setAuthor("ResumePilot")

    state = {"y": H - top, "page": 1}

    def new_page() -> None:
        _footer(c, font, state["page"], W, left, right)
        c.showPage()
        state["page"] += 1
        state["y"] = H - top

    def ensure(space: float) -> None:
        if state["y"] - space < bottom:
            new_page()

    def write(
        text: str,
        size: float,
        color: str,
        *,
        indent: float = 0,
        leading: float | None = None,
        space_after: float = 0,
        strike: bool = False,
    ) -> float:
        leading = leading or size * 1.62
        width = usable - indent
        for ln in _wrap(text, font, size, width):
            ensure(leading)
            state["y"] -= leading
            c.setFont(font, size)
            c.setFillColor(HexColor(color))
            x = left + indent
            c.drawString(x, state["y"], ln)
            if strike:
                tw = c.stringWidth(ln, font, size)
                c.setStrokeColor(HexColor(color))
                c.setLineWidth(0.55)
                c.line(x, state["y"] + size * 0.32, x + tw, state["y"] + size * 0.32)
        state["y"] -= space_after
        return state["y"]

    def heading(title: str) -> None:
        ensure(46)
        state["y"] -= 21
        c.setFont(bold, 9.5)
        c.setFillColor(HexColor(PALETTE["accent"]))
        c.drawString(left, state["y"], title.upper())
        c.setStrokeColor(HexColor(PALETTE["line"]))
        c.setLineWidth(0.7)
        c.line(left, state["y"] - 5, left + usable, state["y"] - 5)
        state["y"] -= 13

    def row(left_text: str, right_text: str, size: float = 10.4) -> None:
        ensure(size * 2.4)
        state["y"] -= size * 1.55
        c.setFont(bold, size)
        c.setFillColor(HexColor(PALETTE["ink"]))
        avail = usable - (c.stringWidth(right_text, font, 8.8) + 14 if right_text else 0)
        label = left_text
        while c.stringWidth(label, bold, size) > avail and len(label) > 4:
            label = label[:-1]
        c.drawString(left, state["y"], label)
        if right_text:
            c.setFont(font, 8.8)
            c.setFillColor(HexColor(PALETTE["sub"]))
            c.drawRightString(left + usable, state["y"], right_text)
        state["y"] -= 6

    def bullet(b: Bullet, indent: float = 0) -> None:
        text = _bullet_text(b, variant)
        if not text.strip():
            return
        if variant == "diff" and b.optimized and b.optimized.strip() != b.original.strip():
            write("- " + b.original, 9.1, PALETTE["red"], indent=indent + 12, leading=13, strike=True)
            write("+ " + b.optimized, 9.5, PALETTE["green"], indent=indent + 12, leading=13.6, space_after=2)
            return
        before = state["y"]
        write(text, 9.5, "#1f2937", indent=indent + 12, leading=13.8)
        # 用真实圆点，避免中文字体缺字导致项目符号丢失
        c.setFillColor(HexColor(PALETTE["sub"]))
        c.circle(left + indent + 3.2, before - 13.8 + 3.1, 1.15, stroke=0, fill=1)

    # ---------------- header ---------------- #
    name = resume.basics.name or "候选人"
    ensure(60)
    state["y"] -= 26
    c.setFont(bold, 22)
    c.setFillColor(HexColor(PALETTE["ink"]))
    c.drawString(left, state["y"], name)
    state["y"] -= 4
    if resume.basics.headline:
        write(resume.basics.headline, 10.2, PALETTE["accent"], leading=16)
    if contact_line(resume):
        write(contact_line(resume), 8.8, PALETTE["sub"], leading=15)
    state["y"] -= 4
    c.setStrokeColor(HexColor(PALETTE["ink"]))
    c.setLineWidth(1.3)
    c.line(left, state["y"], left + usable, state["y"])
    state["y"] -= 2

    # ---------------- body ---------------- #
    if _bullet_text(resume.summary, variant).strip():
        heading("个人简介")
        write(_bullet_text(resume.summary, variant), 9.6, "#1f2937", space_after=4)

    skills_text = _bullet_text(resume.skills, variant)
    if skills_text.strip():
        heading("专业技能")
        write(skills_text.replace("·", " / ").replace("｜", " / "), 9.4, "#334155", space_after=4)

    if resume.experiences:
        heading("工作经历")
        for exp in resume.experiences:
            title = "  |  ".join(x for x in (exp.company, exp.role) if x)
            row(title, exp.period)
            for b in exp.bullets:
                bullet(b)
            state["y"] -= 9

    if resume.projects:
        heading("项目经历")
        for p in resume.projects:
            row("  |  ".join(x for x in (p.name, p.role) if x), p.period)
            for b in p.bullets:
                bullet(b)
            state["y"] -= 9

    if resume.education:
        heading("教育背景")
        for edu in resume.education:
            right_txt = " · ".join(x for x in (edu.degree, edu.period) if x).replace("·", "|")
            row(edu.school, right_txt)
            detail = edu.major or edu.detail
            if detail:
                write(detail, 9.1, PALETTE["sub"], leading=13.4, space_after=2)

    if resume.extras:
        heading("证书 / 荣誉")
        for x in resume.extras[:8]:
            bullet(Bullet(id="x", original=x))

    _footer(c, font, state["page"], W, left, right)
    c.save()
    return buf.getvalue()


def _footer(c, font: str, page: int, W: float, left: float, right: float) -> None:
    from reportlab.lib.colors import HexColor

    c.setFont(font, 7.5)
    c.setFillColor(HexColor("#9ca3af"))
    c.drawString(left, 24, f"ResumePilot · AI 优化生成 · {datetime.now():%Y-%m-%d}")
    text = f"{page}"
    c.drawRightString(W - right, 24, text)


def safe_filename(name: str, ext: str) -> str:
    base = re.sub(r"[\\/:*?\"<>|\s]+", "_", (name or "resume")).strip("_") or "resume"
    return f"{base}_resume.{ext}"
