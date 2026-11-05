import re
import fitz  # PyMuPDF
from ocr.ocr import ocr_page

def extract_text(path: str, min_chars_per_page: int = 80) -> tuple[str, bool]:
    """Returns (text, used_ocr). Pages with almost no text layer are OCR'd."""
    doc = fitz.open(path)
    parts, used_ocr = [], False
    for page in doc:
        t = page.get_text("text")
        if len(t.strip()) < min_chars_per_page:
            o = ocr_page(page)
            if len(o.strip()) > len(t.strip()):
                t, used_ocr = o, True
        parts.append(t)
    return "\n".join(parts), used_ocr

Q_START = re.compile(r"(?m)^\s*(?:Q\.?\s*)?(\d{1,3})[\.\)]\s+(?=\S)")
OPT = re.compile(r"(?m)^\s*\(?([A-D1-4])[\)\.]\s+")

def split_questions(text: str) -> list[dict]:
    """Splits on 1., 2., Q3. ... markers. Sequence checks drop stray numbers (e.g. '2. 5 m/s')."""
    marks = [(int(m.group(1)), m.start(), m.end()) for m in Q_START.finditer(text)]
    keep, expect = [], 1
    for n, s, e in marks:
        if n == expect:
            keep.append((n, s, e)); expect += 1
    out = []
    for i, (n, s, e) in enumerate(keep):
        end = keep[i + 1][1] if i + 1 < len(keep) else len(text)
        body = text[e:end].strip()
        first = OPT.search(body)
        stem = body[:first.start()].strip() if first else body
        options = []
        if first:
            ms = list(OPT.finditer(body))
            for j, m in enumerate(ms):
                options.append({"label": m.group(1), "content": body[m.end(): ms[j + 1].start() if j + 1 < len(ms) else len(body)].strip()})
        out.append({"number": n, "statement": re.sub(r"\s+", " ", stem), "options": options})
    return out

def parse_answer_key(text: str) -> dict[int, str]:
    """Best-effort: reads 'number answer' pairs. Results are stored unverified for human review."""
    key = {}
    for m in re.finditer(r"(?m)\b(\d{1,3})\s*[\.\):\-]?\s+([A-D](?:\s*,\s*[A-D])*|\d+(?:\.\d+)?)\b", text):
        key.setdefault(int(m.group(1)), re.sub(r"\s+", "", m.group(2)))
    return key
