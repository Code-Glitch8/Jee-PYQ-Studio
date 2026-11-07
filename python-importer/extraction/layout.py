"""Layout-aware PDF reading. Every text line keeps its page and position so multi-page questions, figures and
snapshots can be tied back to the page region they came from. Scanned pages are OCR'd with word positions."""
from __future__ import annotations
import io
import re
from collections import Counter
from dataclasses import dataclass, field

try:
    import pymupdf as fitz            # PyMuPDF >= 1.24.3 exposes the `pymupdf` name
except ImportError:                   # pragma: no cover
    import fitz

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
MIN_CHARS_PER_PAGE = 80

@dataclass
class Line:
    text: str
    page: int                         # 1-based
    x0: float
    y0: float
    x1: float
    y1: float
    ocr: bool = False

@dataclass
class PageInfo:
    number: int
    width: float
    height: float
    ocr: bool = False
    chars: int = 0

@dataclass
class PdfContent:
    lines: list[Line] = field(default_factory=list)
    pages: list[PageInfo] = field(default_factory=list)
    ocr_pages: list[int] = field(default_factory=list)
    ocr_unavailable_pages: list[int] = field(default_factory=list)
    dropped_hindi_lines: int = 0
    dropped_header_footer_lines: int = 0

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)

    @property
    def chars(self) -> int:
        return sum(len(l.text.strip()) for l in self.lines)


def _span_text_with_math(spans: list[dict]) -> str:
    """Join spans; small raised/lowered spans become $base^{sup}$ / $base_{sub}$ so exponents and chemical formulae
    survive. Everything else is left alone: we do not try to rebuild full LaTeX from a PDF."""
    if not spans:
        return ""
    body = max(s["size"] for s in spans if s["text"].strip()) if any(s["text"].strip() for s in spans) else spans[0]["size"]
    base_y = None
    out = ""
    for s in spans:
        t = s["text"]
        if not t.strip():
            out += t
            continue
        small = s["size"] < body * 0.8
        raised = bool(s["flags"] & 1)
        if (small or raised) and out.strip() and len(t.strip()) <= 6 and re.fullmatch(r"[\w+\-−=()]+", t.strip()):
            oy = s["origin"][1]
            sup = raised or (base_y is not None and oy < base_y - 1)
            m = re.search(r"(\$[^$]*\$|[A-Za-z0-9)\]]+)$", out)
            if m:
                tok = m.group(1)
                core = tok[1:-1] if tok.startswith("$") else tok
                mark = "^" if sup else "_"
                out = out[: m.start()] + f"${core}{mark}{{{t.strip()}}}$"
                continue
        if not small:
            base_y = s["origin"][1]
        out += t
    return out


def _native_lines(page, number: int) -> list[Line]:
    out = []
    d = page.get_text("dict")
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            txt = _span_text_with_math(ln["spans"]).replace(" ", " ").rstrip()
            if txt.strip():
                x0, y0, x1, y1 = ln["bbox"]
                out.append(Line(txt, number, x0, y0, x1, y1))
    out.sort(key=lambda l: (round(l.y0 / 3), l.x0))     # reading order: top to bottom, then left to right on one baseline
    return _merge_same_baseline(out)


def _merge_same_baseline(lines: list[Line]) -> list[Line]:
    """Fragments on the same visual row (e.g. '1.' in a margin column and the question text) become one line."""
    merged: list[Line] = []
    for l in lines:
        if merged and merged[-1].page == l.page and abs(merged[-1].y0 - l.y0) < 3 and l.x0 >= merged[-1].x1 - 1:
            p = merged[-1]
            gap = " " if l.x0 - p.x1 > 1 else ""
            merged[-1] = Line(p.text + gap + l.text, p.page, p.x0, min(p.y0, l.y0), l.x1, max(p.y1, l.y1), p.ocr)
        else:
            merged.append(l)
    return merged


def ocr_lines(page, number: int, dpi: int = 300) -> list[Line] | None:
    """OCR one page into positioned lines (PDF coordinates). Returns None if OCR is unavailable."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None
    pix = page.get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    try:
        data = pytesseract.image_to_data(img, lang="eng", config="--psm 6", output_type=pytesseract.Output.DICT)
    except Exception:
        return None
    k = 72.0 / dpi
    rows: dict[tuple, list[tuple]] = {}
    for i, w in enumerate(data["text"]):
        if not w.strip() or float(data["conf"][i]) < 0:
            continue
        rows.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(
            (data["left"][i], data["top"][i], data["left"][i] + data["width"][i], data["top"][i] + data["height"][i], w))
    out = []
    for words in rows.values():
        words.sort()
        out.append(Line(" ".join(w[4] for w in words), number, words[0][0] * k, min(w[1] for w in words) * k,
                        words[-1][2] * k, max(w[3] for w in words) * k, ocr=True))
    out.sort(key=lambda l: (l.y0, l.x0))
    return out


def _strip_repeated_margins(content: PdfContent) -> None:
    """Drop running headers/footers/page numbers: short lines in the top/bottom margin that repeat on many pages."""
    n = len(content.pages)
    if n < 2:
        return
    heights = {p.number: p.height for p in content.pages}
    norm = lambda t: re.sub(r"\d+", "#", re.sub(r"\s+", " ", t.strip().lower()))
    counts = Counter(norm(l.text) for l in content.lines if len(l.text) < 120 and (l.y0 < heights[l.page] * 0.08 or l.y1 > heights[l.page] * 0.92))
    repeated = {k for k, c in counts.items() if c >= max(2, n * 0.4)}
    keep = []
    for l in content.lines:
        in_margin = l.y0 < heights[l.page] * 0.08 or l.y1 > heights[l.page] * 0.92
        if in_margin and (norm(l.text) in repeated or re.fullmatch(r"(?:page\s*)?\d{1,3}(?:\s*(?:of|/)\s*\d{1,3})?", l.text.strip(), re.I)):
            content.dropped_header_footer_lines += 1
            continue
        keep.append(l)
    content.lines = keep


def read_pdf(path: str, use_ocr: bool = True, drop_hindi: bool = True) -> PdfContent:
    doc = fitz.open(path)
    content = PdfContent()
    for i, page in enumerate(doc, 1):
        lines = _native_lines(page, i)
        chars = sum(len(l.text.strip()) for l in lines)
        info = PageInfo(i, page.rect.width, page.rect.height, False, chars)
        if chars < MIN_CHARS_PER_PAGE and use_ocr:
            o = ocr_lines(page, i)
            if o is None:
                content.ocr_unavailable_pages.append(i)
            else:
                oc = sum(len(l.text.strip()) for l in o)
                if oc > chars:
                    lines, info.ocr, info.chars = o, True, oc
                    content.ocr_pages.append(i)
        content.pages.append(info)
        content.lines.extend(lines)
    doc.close()
    if drop_hindi:
        keep = []
        for l in content.lines:
            letters = re.findall(r"[^\W\d_]", l.text)
            if letters and len(DEVANAGARI.findall(l.text)) / len(letters) > 0.5:
                content.dropped_hindi_lines += 1
            else:
                keep.append(l)
        content.lines = keep
    _strip_repeated_margins(content)
    return content


def lines_from_text(text: str) -> list[Line]:
    """Plain text -> Lines with synthetic positions (single page). Lets pure-text callers and tests share the parser."""
    return [Line(t.rstrip(), 1, 0.0, float(i * 12), 100.0, float(i * 12 + 10)) for i, t in enumerate(text.splitlines()) if t.strip()]
