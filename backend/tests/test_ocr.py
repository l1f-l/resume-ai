"""扫描件 OCR：判定、识别、降级与报错。"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services import ocr as ocr_mod
from app.services.pdf_parser import PDFParseError, parse_pdf, structure_heuristic


@pytest.fixture
def ocr_on(monkeypatch):
    monkeypatch.setattr(settings, "ocr_enabled", True)
    return settings


def _has_engine() -> bool:
    return bool(ocr_mod.available_engines())


def test_available_engines_shape() -> None:
    engines = ocr_mod.available_engines()
    assert isinstance(engines, list)
    assert all(e in {"tesseract", "rapidocr"} for e in engines)


def test_tidy_removes_spaces_between_cjk() -> None:
    assert ocr_mod._tidy("张 明\n工 作 经 历") == "张明\n工作经历"
    assert ocr_mod._tidy("Python 3.12 版本") == "Python 3.12 版本"


def test_scanned_pdf_is_detected_and_ocrd(scanned_pdf_bytes, ocr_on) -> None:
    if not _has_engine():
        pytest.skip("没有可用的 OCR 引擎（tesseract / rapidocr）")

    parsed = parse_pdf(scanned_pdf_bytes)

    assert parsed.scanned is True
    assert "ocr:" in parsed.method
    assert parsed.ocr_engine in {"tesseract", "rapidocr"}
    assert parsed.ocr_renderer in {"pdf2image", "pymupdf"}
    assert parsed.chars > 150
    assert any("扫描件" in w for w in parsed.warnings)

    # OCR 出来的文本要能继续走结构化，而不是只有一堆乱码
    doc = structure_heuristic(parsed.text)
    assert doc.basics.name == "张明"
    assert "用户增长" in doc.basics.headline
    assert doc.basics.phone == "13800138000"
    assert len(doc.experiences) >= 2
    assert doc.experiences[0].company == "字节跳动"


def test_scanned_pdf_without_ocr_gives_actionable_error(scanned_pdf_bytes, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ocr_enabled", False)
    with pytest.raises(PDFParseError) as exc:
        parse_pdf(scanned_pdf_bytes)
    msg = str(exc.value)
    assert "扫描件" in msg
    assert "OCR" in msg


def test_ocr_failure_message_mentions_install_steps(scanned_pdf_bytes, monkeypatch) -> None:
    """模拟「没有任何 OCR 引擎」，报错要告诉用户装什么。"""
    monkeypatch.setattr(settings, "ocr_enabled", True)
    monkeypatch.setattr(ocr_mod, "available_engines", lambda: [])

    with pytest.raises(ocr_mod.OCRError) as exc:
        ocr_mod.ocr_pdf(scanned_pdf_bytes)
    msg = str(exc.value)
    assert "Tesseract" in msg and "rapidocr" in msg


def test_engine_failure_falls_back_to_next(monkeypatch, scanned_pdf_bytes) -> None:
    """第一个引擎抛错时应继续尝试下一个引擎，而不是直接失败。"""
    monkeypatch.setattr(settings, "ocr_enabled", True)
    monkeypatch.setattr(settings, "ocr_max_pages", 1)
    monkeypatch.setattr(settings, "ocr_dpi", 100)

    calls: list[str] = []

    def boom(_png: bytes) -> str:
        calls.append("boom")
        raise RuntimeError("engine crashed")

    def good(_png: bytes) -> str:
        calls.append("good")
        return "张明 用户增长产品经理 工作经历 字节跳动"

    monkeypatch.setattr(ocr_mod, "available_engines", lambda: ["fake_a", "fake_b"])
    monkeypatch.setitem(ocr_mod.ENGINES, "fake_a", boom)
    monkeypatch.setitem(ocr_mod.ENGINES, "fake_b", good)

    result = ocr_mod.ocr_pdf(scanned_pdf_bytes)
    assert result.engine == "fake_b"
    assert "字节跳动" in result.text
    assert calls == ["boom", "good"]


def test_normal_pdf_does_not_trigger_ocr(pdf_bytes, ocr_on) -> None:
    parsed = parse_pdf(pdf_bytes)
    assert parsed.scanned is False
    assert parsed.ocr_engine == ""
    assert "ocr:" not in parsed.method
