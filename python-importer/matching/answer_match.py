"""Match answer-key entries to imported questions. Pure functions, no database.

A match is only PROPOSED when it is unambiguous: one paper fits the key's year/session/shift/paper number, exactly one
question fits the entry's number (and subject), and the answer's shape fits the question. Everything else is marked
'ambiguous' or 'unmatched' with a reason, and nothing is written to a question. Confirming is a human action."""
from __future__ import annotations
from dataclasses import dataclass, field

DIMENSIONS = ("session", "shift", "paper_number", "exam_date")


@dataclass
class PaperMatch:
    status: str                    # matched | ambiguous | unmatched
    paper: dict | None = None
    candidates: list[dict] = field(default_factory=list)
    note: str = ""


def _same(a, b) -> bool:
    return str(a) == str(b)


def match_paper(doc: dict, papers: list[dict]) -> PaperMatch:
    """doc: source_documents row of the answer key. papers: rows of `papers` (same exam_id)."""
    if doc.get("exam_year") is None:
        return PaperMatch("unmatched", note="the key's exam year is unknown; set it on the document and retry")
    pool = [p for p in papers if p.get("exam_id") == doc.get("exam_id") and p.get("exam_year") == doc.get("exam_year")]
    if not pool:
        return PaperMatch("unmatched", note=f"no question paper for {doc.get('exam_year')} has been imported yet")
    narrowed = pool
    unspecified = []
    for dim in DIMENSIONS:
        want = doc.get(dim)
        if want in (None, ""):
            unspecified.append(dim)
            continue
        if dim == "shift":      # papers.shift may be "<date> S<n>" when the exam date is part of the identity
            narrowed = [p for p in narrowed if _same(p.get("shift"), want) or str(p.get("shift") or "").endswith(f" S{want}")]
        else:
            narrowed = [p for p in narrowed if _same(p.get(dim), want)]
    if not narrowed:
        return PaperMatch("unmatched", candidates=pool, note="no imported paper has the same session/shift/paper number as this key")
    if len(narrowed) == 1:
        extra = [d for d in unspecified if len({str(p.get(d)) for p in pool}) > 1]
        if extra:
            return PaperMatch("ambiguous", candidates=narrowed,
                              note=f"the key does not state {', '.join(extra)} and other papers of that year differ in it; confirm the paper by hand")
        return PaperMatch("matched", narrowed[0], narrowed)
    return PaperMatch("ambiguous", candidates=narrowed, note=f"{len(narrowed)} papers fit this key (missing: {', '.join(unspecified) or 'nothing'}); choose by hand")


def shape_answer(entry: dict, question: dict) -> tuple[object | None, str]:
    """Convert the parsed answer into the exact JSON the question expects. Returns (answer, problem)."""
    a, kind, qtype = entry.get("answer"), entry.get("answer_kind"), question.get("question_type")
    labels = [str(o).upper() for o in question.get("option_labels", [])]
    if a is None or kind in ("unknown", "dropped"):
        return None, "answer could not be read" if kind != "dropped" else "question dropped/bonus in the key; decide by hand"
    if qtype in ("single_mcq", "multi_mcq"):
        if isinstance(a, (int, float)) and not isinstance(a, bool):
            a = [str(int(a))] if float(a) == int(a) else None
        if isinstance(a, list) and labels and all(x.isdigit() for x in labels):     # key says A-D, options are 1-4
            a = [str(ord(x) - 64) if x.isalpha() else x for x in a]
        if isinstance(a, list) and labels and all(x.isalpha() for x in labels):     # key says 1-4, options are A-D
            a = [chr(64 + int(x)) if x.isdigit() else x for x in a]
        if not isinstance(a, list) or not a:
            return None, "answer is not an option choice"
        if qtype == "single_mcq" and len(a) != 1:
            return None, f"{len(a)} options given for a single-correct question"
        if labels and not set(a) <= set(labels):
            return None, f"answer {a} not among the question's options {labels}"
        return sorted(a), ""
    if qtype in ("numerical", "integer"):
        if isinstance(a, list):
            return None, "key gives option letters but the question is numerical"
        if qtype == "integer" and isinstance(a, float) and a != int(a):
            return None, "key gives a decimal for an integer question"
        return a, ""
    return None, f"question type {qtype} cannot be matched automatically"


def match_entries(doc: dict, entries: list[dict], paper: PaperMatch, questions: list[dict]) -> dict[str, dict]:
    """Returns {entry_id: update_fields}. Entries already confirmed/rejected are never touched."""
    updates: dict[str, dict] = {}
    for e in entries:
        if e.get("match_status") in ("confirmed", "rejected"):
            continue
        base = {"paper_id": paper.paper["id"] if paper.paper else None, "matched_question_id": None, "candidate_question_ids": []}
        if paper.status == "unmatched":
            updates[e["id"]] = {**base, "paper_id": None, "match_status": "unmatched", "match_note": paper.note}
            continue
        if paper.status == "ambiguous":
            updates[e["id"]] = {**base, "paper_id": None, "match_status": "ambiguous", "candidate_question_ids": [], "match_note": paper.note}
            continue
        cands = [q for q in questions if q.get("question_number") == e.get("question_number")]
        if e.get("subject_code"):
            cands = [q for q in cands if q.get("subject_code") == e["subject_code"]]
        if e.get("question_number") is None:
            updates[e["id"]] = {**base, "match_status": "unmatched", "match_note": "entry has no question number (id-based key); map it by hand"}
        elif not cands:
            updates[e["id"]] = {**base, "match_status": "unmatched", "match_note": f"question {e['question_number']} was not extracted from the paper"}
        elif len(cands) > 1:
            updates[e["id"]] = {**base, "match_status": "ambiguous", "candidate_question_ids": [q["id"] for q in cands],
                                "match_note": f"{len(cands)} questions share number {e['question_number']} (numbering restarts per subject and the key has no subject headings)"}
        else:
            q = cands[0]
            shaped, problem = shape_answer(e, q)
            if shaped is None:
                updates[e["id"]] = {**base, "match_status": "ambiguous", "candidate_question_ids": [q["id"]], "match_note": problem}
            else:
                updates[e["id"]] = {**base, "match_status": "proposed", "matched_question_id": q["id"], "answer": shaped, "match_note": None}
    return _resolve_conflicts(doc, updates, entries)


def _resolve_conflicts(doc: dict, updates: dict[str, dict], entries: list[dict]) -> dict[str, dict]:
    """Two key documents (provisional and final) can propose different answers for one question. If they agree, fine.
    If they disagree, both stay 'ambiguous' - the importer never decides which key is right."""
    by_q: dict[str, list[str]] = {}
    for eid, u in updates.items():
        if u.get("match_status") == "proposed":
            by_q.setdefault(u["matched_question_id"], []).append(eid)
    for qid, ids in by_q.items():
        if len({str(updates[i]["answer"]) for i in ids}) > 1:
            for i in ids:
                updates[i].update(match_status="ambiguous", candidate_question_ids=[qid], match_note="entries in this key disagree on the answer")
    return updates


def reconcile_across_documents(rows: list[dict], docs: dict[str, dict]) -> dict[str, dict]:
    """rows: entries (existing + new) from ALL key documents. Where two documents propose different answers for the same
    question (e.g. provisional vs final), every involved entry becomes 'ambiguous' with a note naming both versions.
    The importer never decides which key is right."""
    out: dict[str, dict] = {}
    by_q: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("match_status") == "proposed" and r.get("matched_question_id"):
            by_q.setdefault(r["matched_question_id"], []).append(r)
    for qid, rs in by_q.items():
        if len({str(r["answer"]) for r in rs}) > 1:
            versions = ", ".join(sorted({f"{docs.get(r['source_document_id'], {}).get('detected', {}).get('key_version') or 'unversioned'}: {r['raw_answer']}" for r in rs}))
            for r in rs:
                out[r["id"]] = {"match_status": "ambiguous", "match_note": f"key documents disagree ({versions}); review by hand"}
    return out
