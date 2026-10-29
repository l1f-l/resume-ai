"""扫描件 OCR：PDF → 位图 → 文字。

两条渲染链路、两个识别引擎，按可用性自动选择：
  渲染：pdf2image(poppler) → PyMuPDF（纯 pip，无需系统依赖）
  识别：pytesseract(Tesseract) → RapidOCR（onnxruntime，纯 pip，自带中英模型）

之所以做成双链路：Tesseract + poppler 是业界标准方案、识别质量稳定；
但在没有管理员权限的机器上装不了系统依赖时，PyMuPDF + RapidOCR 也能兜住，
保证「扫描件简历」这个场景在任何环境都不是死路。
"""
from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field

from ..config import settings


class OCRError(RuntimeError):
    """OCR 不可用或未识别出内容。"""


@dataclass
class OCRResult:
    text: str = ""
    engine: str = ""
    renderer: str = ""
    pages: int = 0
    warnings: list[str] = field(default_factory=list)


_RAPID_ENGINE = None


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #
def _render_pages(data: bytes) -> tuple[list[bytes], str, int, list[str]]:
    """返回 (每页 PNG 字节, 渲染器名, 页数, 警告)。"""
    warnings: list[str] = []
    dpi = settings.ocr_dpi
    max_pages = settings.ocr_max_pages

    try:
        from pdf2image import convert_from_bytes  # noqa: PLC0415
        from pdf2image.exceptions import (  # noqa: PLC0415
            PDFInfoNotInstalledError,
            PDFPageCountError,
            PDFSyntaxError,
        )

        try:
            images = convert_from_bytes(data, dpi=dpi, fmt="png", last_page=max_pages)
        except (PDFInfoNotInstalledError, PDFPageCountError, PDFSyntaxError) as exc:
            warnings.append(f"pdf2image 渲染失败（poppler 未安装？）：{exc}")
        else:
            out: list[bytes] = []
            for img in images:
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="PNG")
                out.append(buf.getvalue())
            if out:
                return out, "pdf2image", len(images), warnings
    except ImportError:
        warnings.append("未安装 pdf2image")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"pdf2image 异常：{exc}")

    # 兜底：PyMuPDF 渲染，不需要 poppler
    try:
        import pymupdf  # noqa: PLC0415

        doc = pymupdf.open(stream=data, filetype="pdf")
        pages = min(len(doc), max_pages)
        out = []
        for i in range(pages):
            pix = doc[i].get_pixmap(dpi=dpi)
            out.append(pix.tobytes("png"))
        doc.close()
        if out:
            return out, "pymupdf", pages, warnings
        raise OCRError("PDF 没有可渲染的页面")
    except ImportError as exc:
        raise OCRError(
            "无法把 PDF 转成图片：请安装 poppler（配合 pdf2image），"
            "或 pip install pymupdf 作为纯 Python 渲染器"
        ) from exc
    except OCRError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OCRError(f"PDF 渲染失败：{exc}") from exc


# --------------------------------------------------------------------------- #
# 识别引擎
# --------------------------------------------------------------------------- #
def _tesseract_ready() -> bool:
    try:
        import pytesseract  # noqa: PLC0415

        cmd = os.getenv("TESSERACT_CMD")
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001
        return False


def _rapid_ready() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401, PLC0415

        return True
    except Exception:  # noqa: BLE001
        return False


def available_engines() -> list[str]:
    engines = []
    if _tesseract_ready():
        engines.append("tesseract")
    if _rapid_ready():
        engines.append("rapidocr")
    return engines


def _ocr_tesseract(png: bytes) -> str:
    import pytesseract  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    img = Image.open(io.BytesIO(png))
    try:
        return pytesseract.image_to_string(img, lang=settings.ocr_lang)
    except pytesseract.TesseractError:
        # 常见于缺少 chi_sim 语言包，退回英文至少能识别数字与英文
        return pytesseract.image_to_string(img, lang="eng")


def _rapid_lines(payload) -> list[tuple[float, str]]:
    """统一不同版本 rapidocr 的返回结构 → [(y, text)]。"""
    if payload is None:
        return []
    if hasattr(payload, "txts"):  # 新版返回对象
        return [(float(i), str(t)) for i, t in enumerate(payload.txts or [])]
    out: list[tuple[float, str]] = []
    for item in payload:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            box, text = item[0], str(item[1])
            try:
                y = float(box[0][1])
            except (TypeError, ValueError, IndexError):
                y = float(len(out))
            out.append((y, text))
    return out


def _dedupe_lines(lines: list[tuple[float, str]]) -> list[str]:
    """分带识别会有重叠，按纵坐标 + 文本相似度去重。"""
    kept: list[tuple[float, str]] = []
    for y, text in sorted(lines, key=lambda t: t[0]):
        text = text.strip()
        if not text:
            continue
        dup = False
        for ky, ktxt in kept[-3:]:
            if abs(y - ky) > 26:
                continue
            a, b = set(text), set(ktxt)
            overlap = len(a & b) / max(1, min(len(a), len(b)))
            if text in ktxt or ktxt in text or overlap > 0.85:
                dup = True
                break
        if not dup:
            kept.append((y, text))
    return [t for _, t in kept]


def _ocr_rapidocr(png: bytes) -> str:
    """RapidOCR + 横向分带：整页检测容易把相邻两行合并、漏掉细行（如联系方式）。"""
    global _RAPID_ENGINE
    if _RAPID_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415

        _RAPID_ENGINE = RapidOCR()

    try:
        import numpy as np  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        img = Image.open(io.BytesIO(png)).convert("RGB")
        w, h = img.size
        bands = 1 if not settings.ocr_banding or h < 1200 else 4
        step = h // bands
        overlap = 60 if bands > 1 else 0
        collected: list[tuple[float, str]] = []
        for i in range(bands):
            top = max(0, i * step - overlap)
            bottom = min(h, (i + 1) * step + overlap)
            crop = np.array(img.crop((0, top, w, bottom)))[:, :, ::-1]  # RGB → BGR
            out = _RAPID_ENGINE(crop)
            payload = out[0] if isinstance(out, tuple) else out
            collected.extend((y + top, t) for y, t in _rapid_lines(payload))
        return "\n".join(_dedupe_lines(collected))
    except ImportError:
        # 没有 numpy/PIL 时退回整页识别
        out = _RAPID_ENGINE(png)
        payload = out[0] if isinstance(out, tuple) else out
        return "\n".join(t for _, t in _rapid_lines(payload))


ENGINES = {"tesseract": _ocr_tesseract, "rapidocr": _ocr_rapidocr}


def _tidy(text: str) -> str:
    """OCR 常在汉字之间插空格，会破坏关键词匹配，这里收紧。"""
    text = text.replace("\r\n", "\n").replace("\x0c", "\n")
    text = re.sub(r"(?<=[\u4e00-\u9fa5])[ \t]+(?=[\u4e00-\u9fa5])", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def ocr_pdf(data: bytes) -> OCRResult:
    if not settings.ocr_enabled:
        raise OCRError("OCR 已被禁用（OCR_ENABLED=0）")

    engines = available_engines()
    if not engines:
        raise OCRError(
            "未检测到可用的 OCR 引擎。请二选一：\n"
            "  1) 安装 Tesseract（含 chi_sim 语言包）+ poppler，并加入 PATH\n"
            "  2) pip install rapidocr-onnxruntime（纯 Python，自带中英文模型）"
        )

    pages, renderer, page_count, warnings = _render_pages(data)

    last_err = ""
    for name in engines:
        try:
            chunks = [ENGINES[name](png) for png in pages]
            text = _tidy("\n".join(chunks))
            if len(text) >= 10:
                return OCRResult(
                    text=text,
                    engine=name,
                    renderer=renderer,
                    pages=page_count,
                    warnings=warnings,
                )
            last_err = f"{name} 未识别出文字"
        except Exception as exc:  # noqa: BLE001
            last_err = f"{name} 识别失败：{exc}"
            warnings.append(last_err)
            continue

    raise OCRError(f"OCR 未能识别出有效文字（{last_err}）。请确认扫描件清晰、方向正确。")
