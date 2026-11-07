"""Pure functions that read exam metadata (kind, year, session, shift, paper number, date) from a PDF's URL, its link
text, the surrounding page text, or the first pages of the PDF itself. No network access, so everything here is unit
tested. Nothing is guessed: a field that cannot be read stays None and the evidence list says where each value came from.
"""
from __future__ import annotations
import datetime as dt
import re
from urllib.parse import unquote, urlparse

CURRENT_YEAR = dt.date.today().year + 1
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4"}

# Documents that are never question papers or answer keys. First match wins and becomes the skip reason.
NOT_A_PAPER = [
    (r"info(?:rmation)?\s*bulletin|bulletin", "information bulletin"), (r"syllabus", "syllabus"),
    (r"public\s*notice|\bnotice\b|press\s*release|circular|corrigendum", "notice or press release"),
    (r"score\s*card|scorecard|result|rank\s*list|\bcut\s*off|cutoff|topper", "result or scorecard"),
    (r"admit\s*card|city\s*intimation|hall\s*ticket", "admit card"),
    (r"response\s*sheet|recorded\s*response|\bomr\b|candidate\s*response", "candidate response sheet"),
    (r"counsell?ing|josaa|csab|seat\s*(?:matrix|allot)", "counselling document"),
    (r"brochure|\bfaq\b|schedule|time\s*table|guideline|instruction[s]?\s*to\s*candidates|user\s*manual", "brochure, FAQ or schedule"),
    (r"memory[\s-]*based|unofficial|coaching", "memory-based or unofficial paper"),
    (r"b\.?\s*arch|b\.?\s*plan(?:ning)?|\bpaper[\s_-]*2\s*[ab]\b|\bdrawing\b|\baptitude\b", "B.Arch / B.Planning paper (out of scope: not Physics/Chemistry/Mathematics)"),
]
ANSWER_KEY = re.compile(r"answer\s*key|\bkeys?\b|final\s*key|provisional\s*key|\banswers?\b|\bans\b", re.I)
SOLUTION = re.compile(r"\bsolutions?\b|\bsoln\b", re.I)
QUESTION_PAPER = re.compile(r"question\s*paper|\bqp\b|\bpaper\s*[-_ ]*[12]\b|\bp[12]\b|\bpaper\b|\bquestions?\b|\bpyq\b", re.I)
FINAL = re.compile(r"\bfinal\b", re.I)
PROVISIONAL = re.compile(r"provisional|\bdraft\b|\bprelim", re.I)


def normalise(text: str) -> str:
    """Make file names and link text comparable: decode %20, turn _ - . + into spaces, collapse whitespace."""
    t = unquote(text or "")
    t = re.sub(r"[_+]+", " ", t)
    t = re.sub(r"(?<=[A-Za-z])[-.](?=[A-Za-z0-9])|(?<=[0-9])[-.](?=[A-Za-z])", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def file_stem(url: str) -> str:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1]
    return re.sub(r"\.pdf$", "", name, flags=re.I)


def parse_date(text: str) -> dt.date | None:
    """dd.mm.yyyy, dd-mm-yyyy, dd/mm/yyyy, yyyy-mm-dd, '24 Feb 2021', '24th February, 2021'. Day-first for numeric dates."""
    t = unquote(text or "")
    m = re.search(r"(?<!\d)(\d{4})[-_./](\d{1,2})[-_./](\d{1,2})(?!\d)", t)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.search(r"(?<!\d)(\d{1,2})[-_./ ](\d{1,2})[-_./ ](\d{4})(?!\d)", t)
        if m:
            d, mo, y = map(int, m.groups())
        else:
            m = re.search(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s_.-]*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s_.,-]*(\d{4})(?!\d)", t, re.I)
            if not m:
                return None
            d, mo, y = int(m.group(1)), MONTHS[m.group(2).lower()[:3]], int(m.group(3))
    try:
        return dt.date(y, mo, d) if 2002 <= y <= CURRENT_YEAR else None
    except ValueError:
        return None


def find_year(text: str) -> tuple[int | None, str | None]:
    """Returns (year, problem). Two different plausible years in one string is reported, not guessed."""
    years = {int(y) for y in re.findall(r"(?<![0-9])((?:19|20)\d{2})(?![0-9])", text or "") if 2002 <= int(y) <= CURRENT_YEAR}
    if len(years) == 1:
        return years.pop(), None
    if len(years) > 1:
        return None, f"several years in the text: {sorted(years)}"
    return None, None


def find_session(text: str) -> str | None:
    m = re.search(r"\bsession\s*[-:]?\s*([1-4]|iv|iii|ii|i)\b", text, re.I)
    if m:
        v = m.group(1).lower()
        return ROMAN.get(v, v)
    m = re.search(r"\b(?:attempt|phase)\s*[-:]?\s*([1-4])\b", text, re.I)
    return m.group(1) if m else None


def find_shift(text: str) -> str | None:
    m = re.search(r"\bshift\s*[-:]?\s*([12]|ii|i)\b", text, re.I)
    if m:
        v = m.group(1).lower()
        return ROMAN.get(v, v)
    if re.search(r"\b(?:morning|forenoon|fn)\b", text, re.I):
        return "1"
    if re.search(r"\b(?:evening|afternoon|an)\b", text, re.I) and re.search(r"shift|session|paper|slot", text, re.I):
        return "2"
    return None


def find_paper_number(text: str) -> int | None:
    m = re.search(r"\bpaper\s*[-:]?\s*([12])(?![0-9]|\s*[ab]\b)", text, re.I) or re.search(r"(?<![A-Za-z0-9])p\s*([12])(?![0-9A-Za-z])", text, re.I)
    return int(m.group(1)) if m else None


def shift_label(shift: str | None, exam_date: dt.date | None) -> str | None:
    """JEE Main 2019-2022 ran several days per session, each with shift 1 and 2. `papers` is unique on
    (exam, year, session, paper, shift), so when the exam date is known it is part of the stored shift value."""
    if shift is None:
        return exam_date.isoformat() if exam_date else None
    return f"{exam_date.isoformat()} S{shift}" if exam_date else shift


def skip_reason(blob: str) -> str | None:
    for pattern, label in NOT_A_PAPER:
        if re.search(pattern, blob, re.I):
            return label
    return None


def detect_exam(url: str, text: str = "") -> str | None:
    host = urlparse(url).netloc.lower()
    if host.endswith("jeeadv.ac.in"):
        return "jee_advanced"
    blob = f"{url} {text}".lower()
    if re.search(r"jee[\s_()-]*adv", blob):
        return "jee_advanced"
    if host.endswith("jeemain.nta.nic.in") or re.search(r"jee[\s_()-]*main|\bjee\b", blob):
        return "jee_main"
    return None


def classify_document(url: str, link_text: str = "", context: str = "", page_hint: str = "") -> dict:
    """Decide what a PDF link is. `context` is nearby page text (table row, list item, heading) and is only used for
    fields the file name and link text do not give. `page_hint` is the page title/heading and is used last and only
    to supply the year and a question-paper default on pages that are explicitly paper archives."""
    own = normalise(f"{file_stem(url)} {link_text}")
    ctx = normalise(context)
    hint = normalise(page_hint)
    ev: list[str] = []
    out: dict = {"doc_kind": "other", "key_version": None, "exam_year": None, "session": None, "shift": None,
                 "paper_number": None, "exam_date": None, "skip_reason": None, "evidence": ev, "year_problem": None}

    out["skip_reason"] = skip_reason(own)
    if out["skip_reason"]:
        ev.append(f"not a paper: {out['skip_reason']}")
    # Kind: own text first, then the surrounding row/heading.
    for source, text in (("link/file name", own), ("surrounding text", ctx)):
        if out["doc_kind"] != "other":
            break
        if ANSWER_KEY.search(text) and not (SOLUTION.search(text) and not re.search(r"answer\s*key|\bkeys?\b", text, re.I)):
            out["doc_kind"] = "answer_key"
        elif SOLUTION.search(text):
            out["doc_kind"] = "solution"
        elif QUESTION_PAPER.search(text):
            out["doc_kind"] = "question_paper"
        if out["doc_kind"] != "other":
            ev.append(f"kind={out['doc_kind']} from {source}")
    if out["doc_kind"] == "other" and re.search(r"question\s*paper|previous\s*year|past\s*year|archive", hint, re.I):
        out["doc_kind"] = "question_paper"
        ev.append("kind=question_paper inferred from the archive page heading only (low confidence)")
    if out["doc_kind"] == "answer_key":
        both = f"{own} {ctx}"
        out["key_version"] = "final" if FINAL.search(both) and not PROVISIONAL.search(own) else "provisional" if PROVISIONAL.search(both) else None
    if out["doc_kind"] == "other" and not out["skip_reason"]:
        out["skip_reason"] = "could not tell whether this is a question paper, answer key or something else"

    for source, text in (("link/file name", own), ("surrounding text", ctx), ("page heading", hint)):
        year, problem = find_year(text)
        if problem and out["year_problem"] is None:
            out["year_problem"] = f"{source}: {problem}"
        if year and out["exam_year"] is None:
            out["exam_year"] = year
            ev.append(f"year={year} from {source}")
        for field, fn in (("session", find_session), ("shift", find_shift), ("paper_number", find_paper_number)):
            if source != "page heading" and out[field] is None:
                v = fn(text)
                if v is not None:
                    out[field] = v
                    ev.append(f"{field}={v} from {source}")
        if source != "page heading" and out["exam_date"] is None:
            d = parse_date(text)
            if d:
                out["exam_date"] = d
                ev.append(f"date={d} from {source}")
    if out["exam_date"] and out["exam_year"] is None:
        out["exam_year"] = out["exam_date"].year
        ev.append("year taken from the exam date")
    return out


def classify_text(text: str) -> dict:
    """Same fields, read from the first pages of the PDF (title block / header). Used only to fill gaps."""
    head = "\n".join(text.splitlines()[:60])
    blob = normalise(head)
    out = {"exam_year": None, "session": find_session(blob), "shift": find_shift(blob), "paper_number": find_paper_number(blob),
           "exam_date": parse_date(head), "doc_kind": None}
    year, _ = find_year(blob)
    out["exam_year"] = year or (out["exam_date"].year if out["exam_date"] else None)
    if re.search(r"answer\s*key|final\s*key|provisional\s*key", blob, re.I):
        out["doc_kind"] = "answer_key"
    elif re.search(r"(?m)^\s*(?:Q\.?\s*)?1\s*[.)]\s+\S", head) and re.search(r"\(?\b[A-D]\)", head):
        out["doc_kind"] = "question_paper"
    return out


def merge_missing(target: dict, found: dict, source: str, evidence: list[str] | None = None) -> list[str]:
    """Fill only the fields that are still None. Returns the names filled."""
    filled = []
    for k in ("exam_year", "session", "shift", "paper_number", "exam_date"):
        if target.get(k) in (None, "") and found.get(k) not in (None, ""):
            target[k] = found[k]
            filled.append(k)
            if evidence is not None:
                evidence.append(f"{k}={found[k]} from {source}")
    return filled


def classify_pdf(url: str, text: str = "") -> dict:
    """Backwards-compatible wrapper used by older callers and tests."""
    m = classify_document(url, text)
    return {"doc_kind": "answer_key" if m["doc_kind"] == "answer_key" else "question_paper" if m["doc_kind"] == "question_paper" else m["doc_kind"],
            "exam_year": m["exam_year"], "session": m["session"], "shift": m["shift"]}
