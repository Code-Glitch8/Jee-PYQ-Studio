"""Question-paper parsing: lines -> questions.

The hard problem is finding where each question starts without being fooled by numbers inside questions
("2. 5 m/s", a wrapped equation line "3) x + y = 0", a numbered list of instructions). Instead of "first number that
matches the next expected one", every line that *could* start a question is a candidate, each candidate gets a score
from its surroundings, and a dynamic program picks the best consecutive chain 1..N. A candidate that sits in the
middle of a sentence or begins with an operator loses to the real marker; a stretch that contains answer options earns
a bonus, so a numbered instruction list cannot beat the real questions. Missing numbers are reported, never invented.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from extraction.layout import Line, lines_from_text

SUBJECT_WORDS = {"physics": "physics", "chemistry": "chemistry", "mathematics": "mathematics", "maths": "mathematics", "math": "mathematics"}
HEADER_FILLER = {"part", "section", "sec", "subject", "i", "ii", "iii", "iv", "a", "b", "c", "d", "paper", "and"}

MARK_PLAIN = re.compile(r"^\s*(?P<q>(?:Q(?:uestion)?\s*\.?\s*)?)(?P<n>\d{1,3})(?:[.):](?=\s|$))\s*(?P<rest>.*)$", re.I)
MARK_Q = re.compile(r"^\s*(?P<q>Q(?:uestion)?\.?\s*)(?P<n>\d{1,3})(?:\s*[.):\-]\s*|\s+)(?P<rest>.*)$", re.I)
OPT_LINE = re.compile(r"^\s*(?:\(\s*([A-Da-d1-4])\s*\)|([A-D1-4])[.)])\s*(.*)$")
INLINE_OPT = re.compile(r"(?:(?<=\s)|^)\(([A-Da-d1-4])\)\s*")
PARA_START = re.compile(r"^\s*(?:\*+\s*)?(?:paragraph|passage|comprehension|question\s*stem\s*for)\b", re.I)
PARA_RANGE = re.compile(r"(?:nos?\.?|questions?|q\.?)\s*(\d{1,3})\s*(?:and|&|to|-|–|,)\s*(\d{1,3})", re.I)
NOISE_TAIL = re.compile(r"^\s*(?:space\s*for\s*rough\s*work|rough\s*work|end\s*of\s*(?:the\s*)?(?:question\s*)?paper|\*{2,}.*|-{3,}.*)\s*$", re.I)
MATH_CHARS = re.compile(r"[∫∑∏√∞≤≥≠≈±×÷πθλμσΔ∂αβγωφψ∇→]|\$|\^|_\{")
FIGURE_WORDS = re.compile(r"\b(?:figure|fig\.?|diagram|graph|circuit|shown\s+(?:below|above|in))\b", re.I)

HINTS = [  # order matters: first match wins
    ("multi_mcq", re.compile(r"one\s+or\s+more(?:\s+than\s+one)?|more\s+than\s+one\s+(?:of\s+these\s+)?(?:four\s+)?option|multiple[\s-]*correct|multiple[\s-]*select", re.I)),
    ("single_mcq", re.compile(r"only\s+one\s+(?:of\s+(?:these|the)\s+)?(?:four\s+)?option|exactly\s+one|single[\s-]*correct|only\s+one\s+correct", re.I)),
    ("integer", re.compile(r"non[\s-]*negative\s+integer|integer\s+type|integer\s+value|answer\s+is\s+an\s+integer|single[\s-]*digit\s+integer|nearest\s+integer", re.I)),
    ("numerical", re.compile(r"numerical\s+value|decimal|up\s*to\s+(?:the\s+)?(?:2nd|second)", re.I)),
]


def is_subject_header(text: str) -> str | None:
    t = text.strip()
    if not t or len(t) > 70:
        return None
    tokens = re.findall(r"[a-z]+", t.lower())
    subj = [SUBJECT_WORDS[w] for w in tokens if w in SUBJECT_WORDS]
    if subj and all(w in SUBJECT_WORDS or w in HEADER_FILLER for w in tokens):
        return subj[0]
    return None


def is_section_header(text: str) -> bool:
    return bool(re.match(r"^\W*(?:section|part)\b[\s\-–:]*[A-Za-z0-9ivIV]{0,4}\b", text.strip(), re.I)) and len(text.strip()) < 160


def type_hint(text: str) -> str | None:
    for kind, rx in HINTS:
        if rx.search(text):
            return kind
    return None


@dataclass
class Cand:
    n: int
    idx: int
    score: float
    explicit: bool
    rest: str

def _marker(text: str):
    m = MARK_Q.match(text)
    if m:
        return int(m.group("n")), m.group("rest"), True
    m = MARK_PLAIN.match(text)
    if m:
        return int(m.group("n")), m.group("rest"), bool(m.group("q").strip())
    return None


def _score(lines: list[Line], idx: int, rest: str, explicit: bool) -> float:
    s = 0.0
    r = rest.strip()
    if explicit:
        s += 1.5
    if not r:
        s += 0.2
    elif re.match(r"[A-Z][a-z]", r) or re.match(r"(?:If|Let|The|A|An|In|Two|Three|For|Find|Which|What|Match|Consider|Statement|Given)\b", r):
        s += 1.0
    elif re.match(r"\d", r):
        s -= 1.0
    elif re.match(r"[=+\-−*/^<>≤≥(\[|]", r):
        s -= 1.5
    elif re.match(r"[a-z]\s*[=<>+\-−*/^]", r):
        s -= 1.5
    elif re.match(r"[a-z]", r):
        s -= 0.7
    if idx > 0:
        prev = lines[idx - 1].text.rstrip()
        if re.search(r"[,+\-−=(\[{/∫∑√]$|\b(?:of|and|or|the|to|by|with|is|are|at|in|a|an)$", prev, re.I):
            s -= 1.0                      # previous line was cut mid-sentence/equation: this "n." is wrapped text
        elif OPT_LINE.match(prev) or re.search(r"[.?:)\]]$", prev) or is_subject_header(prev) or is_section_header(prev):
            s += 0.5
    return max(-1.4, s)


def _option_labels_at(lines: list[Line]) -> list[str | None]:
    out = []
    for l in lines:
        m = OPT_LINE.match(l.text)
        out.append((m.group(1) or m.group(2)).upper() if m else None)
    return out


def _has_options(labels: list[str | None], a: int, b: int) -> bool:
    seg = {x for x in labels[a:b] if x}
    return ({"A", "B"} <= seg) or ({"1", "2"} <= seg)


def _chain(by_n: dict[int, list[Cand]], start_n: int, labels, boundary_after) -> tuple[float, list[Cand]]:
    """Dynamic program over consecutive question numbers; allows skipping one number (with a penalty)."""
    best: dict[int, tuple[float, Cand | None]] = {}
    top: tuple[float, Cand | None] = (float("-inf"), None)
    for n in sorted(k for k in by_n if k >= start_n):
        for c in by_n[n]:
            end = boundary_after(c)
            bonus = 1.5 if _has_options(labels, c.idx + 1, end) else 0.0
            val = c.score + 1.0 + bonus
            pred, pred_val = None, 0.0 if n == start_n else float("-inf")
            for back, pen in ((1, 0.0), (2, -1.5)):
                for p in by_n.get(n - back, []):
                    if p.idx < c.idx and id(p) in best and best[id(p)][0] + pen > pred_val:
                        pred, pred_val = p, best[id(p)][0] + pen
            if pred_val == float("-inf"):
                continue
            best[id(c)] = (pred_val + val, pred)
            if best[id(c)][0] > top[0]:
                top = (best[id(c)][0], c)
    chain: list[Cand] = []
    cur = top[1]
    while cur is not None:
        chain.append(cur)
        cur = best[id(cur)][1]
    chain.reverse()
    return (top[0] if chain else float("-inf")), chain


@dataclass
class ParsedQuestion:
    number: int
    statement: str
    options: list[dict]
    question_type: str
    subject_hint: str | None
    pieces: list[tuple[int, float, float]]
    page_start: int
    page_end: int
    ocr: bool = False
    warnings: list[str] = field(default_factory=list)
    flags: dict = field(default_factory=dict)

    def asdict(self) -> dict:
        return {"number": self.number, "statement": self.statement, "options": self.options, "question_type": self.question_type,
                "subject_hint": self.subject_hint, "pieces": self.pieces, "page_start": self.page_start, "page_end": self.page_end,
                "ocr": self.ocr, "warnings": self.warnings, "flags": self.flags}


def _split_inline(text: str) -> list[tuple[str, str]] | None:
    ms = list(INLINE_OPT.finditer(text))
    if len(ms) < 2:
        return None
    labels = [m.group(1).upper() for m in ms]
    if labels[0] not in ("A", "1") or any(ord(b) - ord(a) != 1 for a, b in zip(labels, labels[1:])):
        return None
    return [(labels[i], text[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(text)].strip()) for i, m in enumerate(ms)]


def _parse_body(seg: list[Line]) -> tuple[list[str], list[dict]]:
    """Split a question's lines into stem lines and options. Picks the LAST consecutive A-B-C-D / 1-2-3-4 run so a
    list inside the stem ("(A) .. (B) ..") is not mistaken for the options."""
    runs: list[dict] = []
    active = {"alpha": None, "digit": None}
    for i, l in enumerate(seg):
        text = l.text
        inline = _split_inline(text) if re.match(r"^\s*\(", text) else None
        if inline:
            items = inline
        else:
            m = OPT_LINE.match(text)
            items = [((m.group(1) or m.group(2)).upper(), m.group(3).strip())] if m else []
        for label, content in items:
            scheme = "alpha" if label.isalpha() else "digit"
            first = "A" if scheme == "alpha" else "1"
            run = active[scheme]
            if label == first:
                run = {"scheme": scheme, "entries": [(i, label, content)]}
                runs.append(run)
                active[scheme] = run
            elif run is not None and ord(label) - ord(run["entries"][-1][1]) == 1:
                run["entries"].append((i, label, content))
    runs = [r for r in runs if len(r["entries"]) >= 2]
    if not runs:
        return [l.text for l in seg], []
    run = max(runs, key=lambda r: r["entries"][0][0])
    start = run["entries"][0][0]
    options = []
    for k, (i, label, content) in enumerate(run["entries"]):
        stop = run["entries"][k + 1][0] if k + 1 < len(run["entries"]) else len(seg)
        extra = [seg[j].text.strip() for j in range(i + 1, stop)]
        if k == len(run["entries"]) - 1:
            while extra and NOISE_TAIL.match(extra[-1]):
                extra.pop()
        options.append({"label": label, "content": re.sub(r"\s+", " ", " ".join([content] + extra)).strip()})
    return [l.text for l in seg[:start]], options


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_questions(lines: list[Line]) -> tuple[list[ParsedQuestion], dict]:
    """Returns (questions, info). info: missing_numbers, candidates, blocks."""
    n_lines = len(lines)
    labels = _option_labels_at(lines)
    headers = {i: is_subject_header(l.text) for i, l in enumerate(lines)}
    section_idx = [i for i, l in enumerate(lines) if headers[i] or is_section_header(l.text)]
    cands: list[Cand] = []
    for i, l in enumerate(lines):
        mk = _marker(l.text)
        if mk and 0 < mk[0] <= 200:
            n, rest, explicit = mk
            if headers[i] is None:
                cands.append(Cand(n, i, _score(lines, i, rest, explicit), explicit, rest))
    info = {"candidates": len(cands), "missing_numbers": [], "blocks": 0}
    if not cands:
        return [], info

    def boundary_after(c: Cand) -> int:
        nxt = min((x.idx for x in cands if x.n == c.n + 1 and x.idx > c.idx), default=n_lines)
        sec = min((s for s in section_idx if s > c.idx), default=n_lines)
        return min(nxt, sec)

    # Blocks start at each subject header (numbering may restart or continue there).
    starts = [0] + [i for i, h in headers.items() if h and i > 0]
    blocks = [(a, starts[k + 1] if k + 1 < len(starts) else n_lines) for k, a in enumerate(starts)]
    info["blocks"] = len(blocks)
    chosen: list[tuple[Cand, str | None]] = []
    last_n = 0
    for a, b in blocks:
        subject = headers.get(a) or next((headers[i] for i in range(a, min(b, a + 3)) if headers.get(i)), None)
        inb = [c for c in cands if a <= c.idx < b]
        if not inb:
            continue
        by_n: dict[int, list[Cand]] = {}
        for c in inb:
            by_n.setdefault(c.n, []).append(c)
        options = []
        for sn in {1, last_n + 1}:
            if sn in by_n:
                options.append(_chain(by_n, sn, labels, boundary_after))
        if not options:
            sn = min(by_n)
            options.append(_chain(by_n, sn, labels, boundary_after))
        value, chain = max(options, key=lambda t: t[0])
        # Text before the first subject heading is usually the instruction page ("1. Each question has four
        # options ..."). Keep a chain there only if at least one of its items really carries answer options.
        if a == 0 and len(blocks) > 1 and not headers.get(0) and not any(_has_options(labels, c.idx + 1, boundary_after(c)) for c in chain):
            info["discarded_preamble_items"] = len(chain)
            chain = []
        for c in chain:
            chosen.append((c, subject))
        if chain:
            last_n = chain[-1].n
    chosen.sort(key=lambda t: t[0].idx)
    if not chosen:
        return [], info

    nums = [c.n for c, _ in chosen]
    for a, b in zip(nums, nums[1:]):
        if b > a + 1:
            info["missing_numbers"] += list(range(a + 1, b))

    # Section instruction text -> question-type hints.
    hints: list[tuple[int, str | None]] = []
    for s in section_idx:
        nxt = min((c.idx for c, _ in chosen if c.idx > s), default=n_lines)
        block = " ".join(l.text for l in lines[s: min(nxt, s + 14)])
        hints.append((s, type_hint(block)))

    out: list[ParsedQuestion] = []
    pending_passage: list[tuple[str, int | None, int | None]] = []
    for k, (c, subject) in enumerate(chosen):
        nxt = chosen[k + 1][0].idx if k + 1 < len(chosen) else n_lines
        end = min([nxt] + [s for s in section_idx if s > c.idx])
        seg = list(lines[c.idx:end])
        seg[0] = Line(c.rest, seg[0].page, seg[0].x0, seg[0].y0, seg[0].x1, seg[0].y1, seg[0].ocr)
        if not c.rest.strip():
            seg = seg[1:]
        while seg and NOISE_TAIL.match(seg[-1].text):
            seg.pop()
        passage_text = None
        for j, l in enumerate(seg[1:], 1):
            if PARA_START.match(l.text):
                rng = PARA_RANGE.search(l.text)
                pending_passage.append((" ".join(x.text for x in seg[j:]), int(rng.group(1)) if rng else None, int(rng.group(2)) if rng else None))
                seg = seg[:j]
                break
        stem_lines, options = _parse_body(seg)
        stem = _clean(" ".join(stem_lines))
        for ptxt, lo, hi in list(pending_passage):
            if (lo is not None and lo <= c.n <= hi) or (lo is None and passage_text is None):
                passage_text = _clean(ptxt)
        if passage_text:
            stem = f"{passage_text}\n\n{stem}"
        pending_passage = [p for p in pending_passage if p[1] is not None and c.n < p[2]]

        hint = None
        for s, h in hints:
            if s < c.idx:
                hint = h if h else (None if any(headers.get(x) for x in range(s, s + 1)) else hint)
        warnings: list[str] = []
        if re.search(r"\b(?:list|column)[\s-]*(?:i|1)\b", stem, re.I) and re.search(r"\b(?:list|column)[\s-]*(?:ii|2)\b", stem, re.I):
            qtype = "matrix_match"
        elif len(options) >= 2:
            qtype = hint if hint in ("single_mcq", "multi_mcq") else ("multi_mcq" if re.search(r"one\s+or\s+more|more\s+than\s+one|multiple\s+correct", stem, re.I) else "single_mcq")
            if hint in ("integer", "numerical"):
                warnings.append("section says numerical but options were found")
        else:
            if hint in ("single_mcq", "multi_mcq"):
                qtype = hint
                warnings.append("options_not_found")
            else:
                qtype = hint if hint in ("integer", "numerical") else ("integer" if re.search(r"\binteger\b", stem, re.I) else "numerical")
        if qtype in ("single_mcq", "multi_mcq") and len(options) not in (4,) and options:
            warnings.append(f"unexpected_option_count:{len(options)}")
        if len(stem) < 15:
            warnings.append("very_short_statement")
        body = stem + " " + " ".join(o["content"] for o in options)
        ocr = any(l.ocr for l in seg)
        flags = {"math_heavy": len(MATH_CHARS.findall(body)) >= 3, "mentions_figure": bool(FIGURE_WORDS.search(stem)), "ocr": ocr,
                 "paragraph": bool(passage_text)}
        pieces = []
        for pg in sorted({l.page for l in seg}):
            ys = [(l.y0, l.y1) for l in seg if l.page == pg]
            pieces.append((pg, min(y[0] for y in ys), max(y[1] for y in ys)))
        out.append(ParsedQuestion(c.n, stem, options, qtype, subject, pieces, seg[0].page if seg else lines[c.idx].page,
                                  seg[-1].page if seg else lines[c.idx].page, ocr, warnings, flags))
    return out, info


def split_questions(text: str) -> list[dict]:
    """Text-only entry point kept for compatibility. Returns dicts with number, statement, options (+ extra keys)."""
    qs, _ = parse_questions(lines_from_text(text))
    return [q.asdict() for q in qs]
