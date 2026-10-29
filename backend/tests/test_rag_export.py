"""RAG 与导出渲染的单元测试。"""
from __future__ import annotations

from app.services.rag import HashEmbedding, TemplateStore, _cosine
from app.services.pdf_parser import parse_pdf, structure_heuristic
from app.services.exporter import render_html, render_pdf, safe_filename


def test_embedding_is_deterministic_and_normalized() -> None:
    emb = HashEmbedding()
    a = emb(["数据分析 用户增长"])[0]
    b = emb(["数据分析 用户增长"])[0]
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6
    assert _cosine(a, b) > 0.99


def test_template_store_retrieves_relevant(tmp_path) -> None:
    # 指向仓库内置模板目录
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    store = TemplateStore(template_dir=root / "data" / "templates")
    hits = store.search("用户增长 私域 社群运营 GMV ROI 投放", k=3)
    assert len(hits) == 3
    assert hits[0].score >= hits[-1].score
    assert any("运营" in h.title or "增长" in h.title for h in hits)
    assert all(h.snippet for h in hits)


def test_template_store_search_is_scoped(tmp_path) -> None:
    """后端 JD 应该召回后端模板，而不是财务模板。"""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    store = TemplateStore(template_dir=root / "data" / "templates")
    hits = store.search("高并发 微服务 Kubernetes 分布式 QPS", k=2)
    assert "后端" in hits[0].title or "工程" in hits[0].title


def test_template_store_handles_empty_dir(tmp_path) -> None:
    store = TemplateStore(template_dir=tmp_path / "nothing")
    assert store.search("任意查询") == []


def test_render_html_is_self_contained(pdf_bytes: bytes) -> None:
    doc = structure_heuristic(parse_pdf(pdf_bytes).text)
    doc.summary.optimized = "7 年增长经验，擅长用数据定位问题。"
    doc.experiences[0].bullets[0].optimized = "主导抖音电商增长活动，覆盖 320 万用户。"
    html = render_html(doc, "optimized")
    assert html.count("<html") == 1
    assert "<link" not in html and "<script" not in html
    assert "主导抖音电商增长活动" in html
    assert "负责抖音电商的用户增长活动策划与落地" not in html


def test_render_html_variants(pdf_bytes: bytes) -> None:
    doc = structure_heuristic(parse_pdf(pdf_bytes).text)
    doc.experiences[0].bullets[0].optimized = "主导抖音电商增长活动，覆盖 320 万用户。"

    original = render_html(doc, "original")
    assert "负责抖音电商的用户增长活动策划与落地" in original
    assert "主导抖音电商增长活动" not in original

    diff = render_html(doc, "diff")
    assert 'class="del"' in diff and 'class="ins"' in diff
    assert "负责抖音电商的用户增长活动策划与落地" in diff
    assert "主导抖音电商增长活动" in diff


def test_render_pdf_pages_and_text(pdf_bytes: bytes) -> None:
    import io

    from PyPDF2 import PdfReader

    doc = structure_heuristic(parse_pdf(pdf_bytes).text)
    for b in doc.all_bullets():
        b.optimized = b.optimized or b.original
    data = render_pdf(doc, "optimized")
    assert data.startswith(b"%PDF")
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) >= 1
    assert "张明" in "".join(p.extract_text() or "" for p in reader.pages)


def test_safe_filename() -> None:
    assert safe_filename("张 明/简历", "pdf") == "张_明_简历_resume.pdf"
    assert safe_filename("", "html") == "resume_resume.html"
