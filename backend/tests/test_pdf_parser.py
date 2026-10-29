"""PDF 解析与结构化测试。"""
from __future__ import annotations

import io

import pytest

from app.services.pdf_parser import PDFParseError, parse_pdf, structure_heuristic
from app.services.nlp import extract_metrics, split_sections


def test_parse_pdf_extracts_text(pdf_bytes: bytes) -> None:
    parsed = parse_pdf(pdf_bytes)
    assert parsed.ok
    assert parsed.pages == 1
    assert parsed.chars > 200
    assert "张明" in parsed.text
    assert "工作经历" in parsed.text
    assert parsed.method.startswith("pdfplumber")


def test_parse_pdf_keeps_bullet_lines(pdf_bytes: bytes) -> None:
    """条目不能被并成一大段，否则 STAR 重写就失去粒度。"""
    parsed = parse_pdf(pdf_bytes)
    lines = [ln for ln in parsed.text.splitlines() if ln.strip().startswith("-")]
    assert len(lines) >= 8


def test_structure_extracts_basics(pdf_bytes: bytes) -> None:
    doc = structure_heuristic(parse_pdf(pdf_bytes).text)
    assert doc.basics.name == "张明"
    assert doc.basics.email == "zhangming@example.com"
    assert doc.basics.phone == "13800138000"
    assert "用户增长" in doc.basics.headline


def test_structure_splits_experiences(pdf_bytes: bytes) -> None:
    doc = structure_heuristic(parse_pdf(pdf_bytes).text)
    assert len(doc.experiences) == 2
    first, second = doc.experiences
    assert first.company == "字节跳动"
    assert first.period.startswith("2021.03")
    assert len(first.bullets) == 4
    assert second.company == "小红书"
    assert len(second.bullets) == 3


def test_structure_ids_are_unique(pdf_bytes: bytes) -> None:
    doc = structure_heuristic(parse_pdf(pdf_bytes).text)
    ids = [b.id for b in doc.all_bullets()]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 9


def test_structure_education_and_sections(pdf_bytes: bytes) -> None:
    text = parse_pdf(pdf_bytes).text
    doc = structure_heuristic(text)
    assert doc.education and doc.education[0].school == "复旦大学"
    assert doc.education[0].degree == "本科"
    assert "信息管理" in doc.education[0].major
    # 教育详情不应把学校名重复一遍
    assert doc.education[0].detail == ""
    assert split_sections(text)["skills"]


def test_parse_pdf_rejects_non_pdf() -> None:
    with pytest.raises(PDFParseError):
        parse_pdf(b"this is not a pdf")
    with pytest.raises(PDFParseError):
        parse_pdf(b"")


def test_parse_pdf_rejects_blank_pdf() -> None:
    """只有空白页的 PDF 应当报「无法提取文字」，而不是返回空简历。"""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.showPage()
    c.save()
    with pytest.raises(PDFParseError) as exc:
        parse_pdf(buf.getvalue())
    assert "扫描件" in str(exc.value)


def test_metric_extraction() -> None:
    assert extract_metrics("GMV 提升 28%，覆盖 320 万用户") == ["28%", "320 万"]
    assert extract_metrics("没有数字的一句话") == []
