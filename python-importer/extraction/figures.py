"""Figures and question snapshots.

* Figures: embedded raster images and clusters of vector drawing (circuits, graphs, geometry) larger than a threshold,
  rendered as PNG and attached to the question whose page region contains them.
* Snapshots: a PNG of the question's own page region. Created only for questions that need a visual cross-check
  (OCR text, heavy mathematics, or a figure reference), so an admin can compare the extracted text with the paper.
"""
from __future__ import annotations
try:
    import pymupdf as fitz
except ImportError:                   # pragma: no cover
    import fitz

MIN_W, MIN_H = 40.0, 30.0


def _union(rects):
    merged = []
    for r in rects:
        r = fitz.Rect(r)
        for i, m in enumerate(merged):
            if m.intersects(r + (-6, -6, 6, 6)):
                merged[i] = m | r
                break
        else:
            merged.append(r)
    return merged


def find_figures(page) -> list:
    """Figure rectangles on one (text) page, in page coordinates."""
    area = page.rect.width * page.rect.height
    found = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") == 1:
            found.append(fitz.Rect(b["bbox"]))
    if hasattr(page, "cluster_drawings"):
        try:
            found.extend(fitz.Rect(r) for r in page.cluster_drawings())
        except Exception:
            pass
    ok = [r for r in found if r.width >= MIN_W and r.height >= MIN_H and r.width * r.height < 0.6 * area
          and max(r.width / max(r.height, 1), r.height / max(r.width, 1)) < 25]
    return _union(ok)


def render(page, rect, dpi: int = 200) -> bytes:
    clip = fitz.Rect(rect) + (-4, -4, 4, 4)
    clip &= page.rect
    return page.get_pixmap(clip=clip, dpi=dpi).tobytes("png")


def collect(path: str, questions: list[dict], ocr_pages: set[int]) -> dict[int, list[dict]]:
    """questions: [{'number', 'pieces': [(page, y0, y1)], 'needs_snapshot': bool}] (index-aligned).
    Returns {index: [{'kind': 'figure'|'snapshot', 'page': n, 'png': bytes}]}."""
    out: dict[int, list[dict]] = {}
    doc = fitz.open(path)
    try:
        figs = {p: find_figures(doc[p - 1]) for p in {pg for q in questions for pg, _, _ in q["pieces"]} if p not in ocr_pages}
        for qi, q in enumerate(questions):
            items = []
            for pg, y0, y1 in q["pieces"]:
                page = doc[pg - 1]
                for r in figs.get(pg, []):
                    cy = (r.y0 + r.y1) / 2
                    if y0 - 4 <= cy <= y1 + 30:
                        items.append({"kind": "figure", "page": pg, "png": render(page, r)})
                if q.get("needs_snapshot"):
                    items.append({"kind": "snapshot", "page": pg, "png": render(page, fitz.Rect(0, max(0, y0 - 4), page.rect.width, min(page.rect.height, y1 + 8)), 150)})
            if items:
                out[qi] = items
    finally:
        doc.close()
    return out
