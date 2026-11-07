"""Answer-key parsing. Produces *entries* (one per answer) that are stored in `answer_key_entries`. Nothing here decides
which question an entry belongs to; that is `matching.answer_match`. Anything unclear is kept as raw text with
answer=None so a person can resolve it. Conflicting duplicates are never resolved by guessing."""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from extraction.layout import Line, lines_from_text
from extraction.questions import is_subject_header

LETTERS = r"[A-D](?:\s*[,;&/]\s*[A-D]|\s+(?:and|&)\s+[A-D])*|[A-D]{2,4}"
NUMBER = r"[-+−]?\d+(?:\.\d+)?"
RANGE = rf"{NUMBER}\s*(?:to|-|–|—)\s*{NUMBER}"
DROPPED = r"DROP(?:PED)?|BONUS|ALL|N/?A|X|\*|--+|–"
ANSWER = rf"(?P<a>{RANGE}|{LETTERS}|{NUMBER}|{DROPPED})"
PAIR = re.compile(rf"(?:Q\.?\s*)?(?P<n>\d{{1,3}})\s*(?:[.):|\-–—]|\s)\s*\(?{ANSWER.replace('(?P<a>', '(?P<a>', 1)}\)?(?=\s|$|[,;|])", re.I)
ID_ROW = re.compile(rf"^\s*(?:(?P<n>\d{{1,3}})\s+)?(?P<id>\d{{6,}})\s+(?P<a>\d{{6,}}(?:\s*[,;]\s*\d{{6,}})*|{ANSWER[7:-1]})\s*$", re.I)
HEADER_WORDS = re.compile(r"\b(?:question|q\.?\s*no|sl\.?\s*no|answer|ans|key|correct|option|section|paper|subject|marks?)\b", re.I)


@dataclass
class KeyEntry:
    question_number: int | None
    raw_answer: str
    answer: list[str] | float | dict | None
    kind: str                      # single | multiple | numerical | unknown | dropped
    subject_code: str | None = None
    original_question_id: str | None = None
    page: int | None = None
    note: str | None = None

    def asdict(self) -> dict:
        return self.__dict__.copy()


def _num(s: str) -> float:
    return float(s.replace("−", "-").replace("+", ""))


def normalise_answer(raw: str) -> tuple[object, str]:
    """('B' -> (['B'],'single')), ('A,C' -> (['A','C'],'multiple')), ('12.5' -> (12.5,'numerical')),
    ('12.3-12.5' -> ({'value':12.4,'tolerance':0.1},'numerical')), ('DROPPED' -> (None,'dropped'))."""
    r = raw.strip().strip("()")
    if re.fullmatch(DROPPED, r, re.I):
        return None, "dropped"
    if re.fullmatch(RANGE, r):
        a, b = [_num(x) for x in re.split(r"\s*(?:to|-|–|—)\s*(?=[-+−]?\d)", r, maxsplit=1)]
        lo, hi = min(a, b), max(a, b)
        return ({"value": round((lo + hi) / 2, 6), "tolerance": round((hi - lo) / 2, 6)} if hi > lo else lo), "numerical"
    if re.fullmatch(NUMBER, r):
        v = _num(r)
        return (int(v) if v == int(v) and "." not in r else v), "numerical"
    if re.fullmatch(LETTERS, r, re.I):
        letters = sorted(set(re.findall(r"[A-D]", r.upper())))
        return letters, "single" if len(letters) == 1 else "multiple"
    return None, "unknown"


def _clean_line(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace(" ", " ")).strip()


def parse_key_lines(lines: list[Line]) -> tuple[list[KeyEntry], dict]:
    entries: list[KeyEntry] = []
    subject: str | None = None
    i = 0
    skipped_lines = 0
    while i < len(lines):
        l = lines[i]
        text = _clean_line(l.text)
        subj = is_subject_header(text)
        if subj:
            subject = subj
            i += 1
            continue
        # Row-wise tables: a line of consecutive question numbers followed by a line of answers.
        toks = re.sub(r"^(?:q(?:uestion)?\.?\s*(?:no\.?)?|no\.?|sl\.?\s*no\.?)\s*[:\-]?\s*", "", text, flags=re.I).split()
        if len(toks) >= 3 and all(re.fullmatch(r"\d{1,3}", t) for t in toks) and i + 1 < len(lines):
            nums = [int(t) for t in toks]
            if all(b == a + 1 for a, b in zip(nums, nums[1:])):
                ans_line = _clean_line(re.sub(r"^(?:ans(?:wer)?s?\.?|key)\s*[:\-]?\s*", "", _clean_line(lines[i + 1].text), flags=re.I))
                ans = ans_line.split()
                if len(ans) == len(nums):
                    for n, a in zip(nums, ans):
                        v, kind = normalise_answer(a)
                        entries.append(KeyEntry(n, a, v, kind, subject, None, l.page))
                    i += 2
                    continue
        m = ID_ROW.match(text)
        if m:
            raw = re.sub(r"\s+", "", m.group("a"))
            entries.append(KeyEntry(int(m.group("n")) if m.group("n") else None, raw, None, "unknown", subject, m.group("id"), l.page,
                                    "answer given as an official option id; map it to an option by hand"))
            i += 1
            continue
        pairs = list(PAIR.finditer(text))
        # A line that is mostly prose is not a key row (this is what polluted the old parser with "solutions" PDFs).
        residue = PAIR.sub(" ", text)
        if pairs and len(re.findall(r"[A-Za-z]{4,}", residue)) <= 2:
            for p in pairs:
                raw = p.group("a")
                v, kind = normalise_answer(raw)
                entries.append(KeyEntry(int(p.group("n")), raw.strip(), v, kind, subject, None, l.page))
        elif text and not HEADER_WORDS.search(text):
            skipped_lines += 1
        i += 1

    # Duplicates inside one key: identical -> keep one; conflicting -> keep none usable (never guess which is right).
    by_key: dict[tuple, list[KeyEntry]] = {}
    for e in entries:
        by_key.setdefault((e.subject_code, e.question_number, e.original_question_id), []).append(e)
    final: list[KeyEntry] = []
    conflicts = 0
    for group in by_key.values():
        first = group[0]
        if len(group) > 1 and any(str(g.answer) != str(first.answer) or g.kind != first.kind for g in group[1:]):
            conflicts += 1
            first.answer, first.kind = None, "unknown"
            first.raw_answer = " / ".join(dict.fromkeys(g.raw_answer for g in group))
            first.note = "the key lists different answers for this question number; resolve by hand"
        final.append(first)
    return final, {"rows": len(final), "conflicts": conflicts, "ignored_lines": skipped_lines}


def parse_answer_key_entries(text: str) -> tuple[list[KeyEntry], dict]:
    return parse_key_lines(lines_from_text(text))


def parse_answer_key(text: str) -> dict[int, str]:
    """Compatibility wrapper: {question_number: raw answer} for the first entry of each number."""
    out: dict[int, str] = {}
    for e in parse_answer_key_entries(text)[0]:
        if e.question_number is not None:
            out.setdefault(e.question_number, re.sub(r"\s+", "", e.raw_answer))
    return out


def key_looks_valid(entries: list[KeyEntry], info: dict) -> tuple[bool, str]:
    """A real key has many rows and few ignored prose lines. Rejects solution PDFs and noise."""
    usable = [e for e in entries if e.question_number is not None]
    if len(usable) < 5:
        return False, f"only {len(usable)} answer row(s) recognised (need at least 5); this does not look like an answer-key table"
    if info.get("ignored_lines", 0) > 3 * len(usable):
        return False, f"{info['ignored_lines']} prose lines vs {len(usable)} answer rows; looks like a solutions/explanation document, not a key"
    return True, ""
