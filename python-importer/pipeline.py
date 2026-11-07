"""The import pipeline.

Document statuses (source_documents.import_status), in order:
    discovered -> downloaded -> extracted -> classified -> awaiting_review -> completed        (or skipped / failed)
Question papers: extracted = questions stored (subject from the paper's headings); classified = AI chapter/difficulty
assigned; awaiting_review = waiting for an admin; completed = the paper is published.
Answer keys:     extracted = entries stored; awaiting_review = entries matched/pending a person; completed = all confirmed.
A document only reaches `completed` through a person. A key never advances a question paper's status.
"""
from __future__ import annotations
import hashlib
import os
import re
import tempfile
import traceback
from dataclasses import dataclass

from dedupe import fingerprint, near_duplicates
from extraction import figures
from extraction.answer_key import key_looks_valid, parse_key_lines
from extraction.layout import read_pdf
from extraction.questions import parse_questions
from matching.answer_match import match_entries, match_paper, reconcile_across_documents
from report import Stats, outcome, summary, write_github_summary
from sources.crawler import Fetcher, crawl
from sources.metadata import classify_text, merge_missing, shift_label

MIN_TEXT_CHARS = 60
LOW_CONFIDENCE = 0.75
SUBJECT_CODES = ("physics", "chemistry", "mathematics")


@dataclass
class Config:
    mode: str = "full"                  # full | discover_only | process_only | retry_failed
    max_depth: int = 3
    max_pages: int = 60
    max_downloads: int = 80
    document_id: str | None = None
    only_if_queued: bool = False
    delay: float = 3.0
    classify_delay: float = 0.4


class Pipeline:
    def __init__(self, store, fetcher: Fetcher, classify_fn=None, config: Config | None = None, trigger: str = "manual", sleep=None, seeds=None):
        self.s, self.f, self.classify_fn, self.cfg, self.trigger = store, fetcher, classify_fn, config or Config(), trigger
        self.seeds = seeds
        self.stats = Stats()
        self.run_id = None
        self.crawl_result = None
        import time
        self._sleep = sleep or time.sleep

    # ------------------------------------------------------------------ logging / status helpers
    def log(self, level, message, details=None, doc=None):
        print(f"[{level}] {message}")
        self.s.log(self.run_id, level, message, details, doc["id"] if isinstance(doc, dict) else doc)

    def set_status(self, doc: dict, status: str, reason: str | None = None, job: dict | None = None, **fields):
        """Single place where a document changes state; every change is logged with its reason."""
        self.s.update_document(doc["id"], {"import_status": status, "status_reason": reason, "last_run_id": self.run_id, **fields})
        doc.update(import_status=status, status_reason=reason, **fields)
        if job is not None:
            self.s.update_job(job["id"], {"status": status, "last_error": reason if status in ("failed", "skipped") else None})
        level = "error" if status == "failed" else "warn" if status == "skipped" else "info"
        self.log(level, f"{_name(doc)} -> {status}" + (f": {reason}" if reason else ""), {"stage": "status", "status": status, "reason": reason, "url": doc.get("source_url")}, doc)
        if status == "failed":
            self.stats.add("documents_failed")
        elif status == "skipped":
            self.stats.add("documents_skipped")

    # ------------------------------------------------------------------ run
    def run(self) -> Stats:
        if self.s.setting("import_paused", False):
            print("Imports are paused in Admin settings.")
            return self.stats
        run = self.s.claim_run(self.trigger, self.cfg.mode, self.cfg.only_if_queued)
        if run is None:
            print("No queued run; nothing to do.")
            return self.stats
        self.run_id = run["id"]
        mode = run.get("mode") or self.cfg.mode
        if self.cfg.mode != "full" and mode == "full":
            mode = self.cfg.mode
        self.mode = mode
        status = "completed"
        try:
            if mode in ("full", "discover_only"):
                self.discover()
            if mode in ("full", "process_only", "retry_failed"):
                if mode in ("full", "retry_failed"):
                    self.download()
                self.process_jobs()
            self.match_all()
            self.refresh_completion()
        except Exception as e:                       # the run itself broke: record it and say so
            self.log("error", f"Run aborted: {e}", {"traceback": traceback.format_exc()[-1500:]})
            status = "failed"
        code, why = outcome(self.stats, mode, getattr(self.crawl_result, "seeds_total", 0) if self.crawl_result else 0,
                            getattr(self.crawl_result, "seeds_reached", 0) if self.crawl_result else 0)
        text = summary(self.stats, mode, code, why, self.s.snapshot_counts())
        print("\n" + text)
        write_github_summary(text)
        self.log("info", f"Run finished: {code}", {"stage": "summary", "outcome": code, "explanation": why})
        self.s.finish_run(self.run_id, status, {**self.stats, "outcome": code, "explanation": why, "mode": mode})
        self.outcome = code
        return self.stats

    # ------------------------------------------------------------------ 1. discovery
    def discover(self):
        cb = lambda level, message, details=None: self.log(level, message, details or {})
        kw = {"seeds": self.seeds} if self.seeds else {}
        res = crawl(self.f, cb, max_depth=self.cfg.max_depth, max_pages_per_seed=self.cfg.max_pages, **kw)
        self.crawl_result = res
        self.stats["pages_crawled"] = res.pages_visited
        exams = self.s.exams()
        for d in res.documents:
            self.stats.add("pdfs_discovered")
            existing = self.s.get_document_by_url(d.url)
            if existing:
                self.s.update_document(existing["id"], {"source_page_url": d.page_url, "link_text": d.link_text[:300], "last_run_id": self.run_id})
                continue
            m = d.meta
            exam_date = m["exam_date"]
            row = {"exam_id": exams.get(d.exam) if d.exam else None, "doc_kind": m["doc_kind"] if m["doc_kind"] in ("question_paper", "answer_key", "solution") else "other",
                   "source_url": d.url, "source_page_url": d.page_url, "link_text": d.link_text[:300], "discovery_depth": d.depth,
                   "origin": "official_site", "status": "official", "exam_year": m["exam_year"], "session": m["session"],
                   "shift": shift_label(m["shift"], exam_date), "paper_number": int(m["paper_number"]) if m["paper_number"] else None, "exam_date": exam_date,
                   "detected": {"evidence": m["evidence"], "key_version": m["key_version"], "year_problem": m["year_problem"], "context": d.context[:300]},
                   "import_status": "skipped" if d.skip_reason else "discovered", "status_reason": d.skip_reason, "last_run_id": self.run_id}
            doc = self.s.insert_document(row)
            self.stats.add("pdfs_new")
            if d.skip_reason:
                self.stats.add("documents_skipped")
                self.log("warn", f"{_name(doc)} discovered and skipped: {d.skip_reason}", {"stage": "discover", "url": d.url, "reason": d.skip_reason}, doc)
            else:
                self.log("info", f"{_name(doc)} discovered", {"stage": "discover", "url": d.url, "page": d.page_url}, doc)
        if not res.documents:
            blocked = [f"{x['url']} ({x['reason']})" for x in res.failures][:6]
            self.log("warn", "Discovery found no PDF links." + (f" Pages that could not be read: {'; '.join(blocked)}" if blocked else ""), {"stage": "discover", "failures": res.failures[:20]})

    # ------------------------------------------------------------------ 2. download
    def download(self):
        todo = self.s.documents_with_status(["discovered"])
        if self.cfg.document_id:
            todo = [d for d in todo if d["id"] == self.cfg.document_id]
        todo = [d for d in todo if d.get("source_url")]
        if len(todo) > self.cfg.max_downloads:
            self.log("warn", f"{len(todo)} documents waiting; downloading {self.cfg.max_downloads} this run (raise --max-downloads).", {"stage": "download"})
        exams = {v: k for k, v in self.s.exams().items()}
        for d in todo[: self.cfg.max_downloads]:
            r = self.f.get(d["source_url"], "pdf")
            if not r.ok:
                hint = "" if "Manual upload" in r.message or r.reason not in ("blocked", "rate_limited", "robots_disallowed", "challenge_page", "login_wall", "host_dropped") \
                    else " Not bypassed: download the PDF yourself and use Manual upload in Admin."
                self.set_status(d, "failed", f"download {r.reason}: {r.message}{hint}", self.s.ensure_job(d["id"], self.run_id))
                continue
            if not r.content.startswith(b"%PDF"):
                self.set_status(d, "failed", f"download not_a_pdf: the link returned {r.content_type or 'unknown content'} instead of a PDF (login/error page?)", self.s.ensure_job(d["id"], self.run_id))
                continue
            sha = hashlib.sha256(r.content).hexdigest()
            dup = self.s.find_by_sha(sha)
            if dup and dup["id"] != d["id"]:
                self.set_status(d, "skipped", f"duplicate: identical file (SHA-256) already stored as {_name(dup)} [{dup['id'][:8]}]")
                continue
            path = f"{exams.get(d['exam_id'], 'other')}/{sha[:16]}.pdf"
            try:
                self.s.put_source(path, r.content)
            except Exception as e:
                self.set_status(d, "failed", f"storage_error: could not store the PDF: {e}", self.s.ensure_job(d["id"], self.run_id))
                continue
            self.set_status(d, "downloaded", None, None, sha256=sha, storage_path=path, file_size_bytes=len(r.content))
            self.s.ensure_job(d["id"], self.run_id)
            self.stats.add("answer_keys_downloaded" if d["doc_kind"] == "answer_key" else "question_papers_downloaded")

    # ------------------------------------------------------------------ 3. extraction / classification
    def process_jobs(self):
        for job in self.s.pending_jobs(self.cfg.document_id):
            if self.s.setting("import_paused", False):
                self.log("info", "Paused mid-run by an administrator.")
                break
            doc = self.s.get_document(job["document_id"])
            self.s.update_job(job["id"], {"status": "running", "attempts": job["attempts"] + 1, "run_id": self.run_id})
            if not doc or not doc.get("storage_path"):
                if doc:
                    self.set_status(doc, "failed", "no stored PDF to process (download first, or upload the file manually)", job)
                continue
            if doc["import_status"] in ("skipped",) and doc["origin"] != "manual_upload":
                self.s.update_job(job["id"], {"status": "skipped"})
                continue
            try:
                self.process_document(doc, job)
            except Exception as e:
                self.log("error", f"Unexpected error: {e}", {"traceback": traceback.format_exc()[-1500:], "stage": "process"}, doc)
                self.set_status(doc, "failed", f"unexpected error: {type(e).__name__}: {e}"[:500], job)

    def process_document(self, doc: dict, job: dict):
        blob = self.s.get_source(doc["storage_path"])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "doc.pdf")
            with open(path, "wb") as fh:
                fh.write(blob)
            try:
                content = read_pdf(path)
            except Exception as e:
                return self.set_status(doc, "failed", f"extract_error: the PDF could not be opened ({type(e).__name__}: {e})", job)
            if content.chars < MIN_TEXT_CHARS:
                why = "no text found"
                if content.ocr_unavailable_pages:
                    why += f"; {len(content.ocr_unavailable_pages)} page(s) look scanned but OCR is not available (install tesseract-ocr)"
                elif content.ocr_pages:
                    why += "; OCR ran but found almost nothing readable"
                return self.set_status(doc, "failed", f"extract_error: {why}. Upload a cleaner copy manually.", job, page_count=len(content.pages), ocr_used=bool(content.ocr_pages))
            self.s.update_document(doc["id"], {"page_count": len(content.pages), "ocr_used": bool(content.ocr_pages)})
            doc.update(page_count=len(content.pages), ocr_used=bool(content.ocr_pages))
            found = classify_text(content.text)
            ev: list[str] = []
            filled = merge_missing(doc, found, "the PDF's first page", ev)
            if filled:
                self.s.update_document(doc["id"], {k: doc[k] for k in filled})
                self.log("info", f"Filled {', '.join(filled)} from the PDF text", {"evidence": ev, "stage": "extract"}, doc)

            kind = doc["doc_kind"]
            if kind == "solution":
                return self.set_status(doc, "skipped", "solutions document: solutions are never imported automatically", job)
            key_entries, key_info = parse_key_lines(content.lines)
            key_ok, key_why = key_looks_valid(key_entries, key_info)
            questions, qinfo = parse_questions(content.lines)
            q_ok = len(questions) >= 3 and sum(1 for q in questions if q.options) >= 2 or len(questions) >= 10
            if kind in ("question_paper", "other") and not q_ok and key_ok and len(key_entries) >= 10:
                self.log("warn", "Named like a question paper but reads like an answer key; treating it as an answer key", {"stage": "extract"}, doc)
                kind = "answer_key"
            elif kind in ("answer_key", "other") and not key_ok and q_ok:
                self.log("warn", "Named like an answer key but reads like a question paper; treating it as a question paper", {"stage": "extract"}, doc)
                kind = "question_paper"
            if kind != doc["doc_kind"]:
                self.s.update_document(doc["id"], {"doc_kind": kind})
                doc["doc_kind"] = kind
            if kind == "answer_key":
                return self._store_key(doc, job, key_entries, key_info, key_ok, key_why)
            if kind == "question_paper":
                return self._store_questions(doc, job, content, questions, qinfo, path)
            return self.set_status(doc, "skipped", "could not recognise this PDF as a question paper or an answer key", job)

    # ---- answer keys
    def _store_key(self, doc, job, entries, info, ok, why):
        if not ok:
            code = "skipped" if info.get("ignored_lines", 0) > 3 * max(1, len(entries)) else "failed"
            return self.set_status(doc, code, f"not a usable answer key: {why}", job, )
        rows = [{"exam_id": doc["exam_id"], "exam_year": doc.get("exam_year"), "session": doc.get("session"), "shift": doc.get("shift"), "paper_number": doc.get("paper_number"),
                 "subject_code": e.subject_code, "question_number": e.question_number, "original_question_id": e.original_question_id,
                 "raw_answer": e.raw_answer[:200], "answer": e.answer, "answer_kind": e.kind, "source_page": e.page, "match_note": e.note} for e in entries]
        n = self.s.replace_entries(doc["id"], rows)
        self.stats.add("answer_entries_extracted", n)
        self.s.update_job(job["id"], {"answer_rows": n})
        self.log("info", f"Stored {n} answer-key entries ({info['conflicts']} conflicting duplicates left unresolved)", {"stage": "extract", **info}, doc)
        self.set_status(doc, "extracted", f"{n} answer-key entries stored; waiting to be matched to a question paper", job)

    # ---- question papers
    def _store_questions(self, doc, job, content, questions, qinfo, pdf_path):
        if not doc.get("exam_year"):
            prob = (doc.get("detected") or {}).get("year_problem")
            return self.set_status(doc, "failed", "missing_year: the exam year could not be read" + (f" ({prob})" if prob else "") + ". Set it on the document in Admin, then retry.", job)
        if not questions:
            return self.set_status(doc, "failed", f"no_questions_found: no question markers recognised ({qinfo['candidates']} candidate lines, {len(content.lines)} text lines). Check the PDF in Admin or upload a cleaner copy.", job)
        if qinfo.get("missing_numbers"):
            self.log("warn", f"Question numbers missing from the extraction: {qinfo['missing_numbers'][:30]}", {"stage": "extract", "missing": qinfo["missing_numbers"]}, doc)
        paper, created = self.s.find_or_create_paper({"exam_id": doc["exam_id"], "exam_year": doc["exam_year"], "session": doc.get("session"), "paper_number": doc.get("paper_number") or 1,
                                                       "shift": doc.get("shift"), "exam_date": doc.get("exam_date"), "source_url": doc.get("source_url"), "source_document_id": doc["id"],
                                                       "source_status": doc.get("status") if doc.get("status") in ("official", "verified_archive") else "awaiting_verification"})
        self.log("info", f"{'Created' if created else 'Using existing'} paper {_paper_name(paper)} ({len(questions)} questions parsed)", {"stage": "extract", "paper_id": paper["id"]}, doc)
        tax = self.s.taxonomy()
        code_to_id = {s["code"]: s["id"] for s in tax["subjects"].values()}
        exam_code = next((k for k, v in self.s.exams().items() if v == doc["exam_id"]), "exam")
        chapter_ids = {(c["subject_id"], c["name"]): c["id"] for c in tax["chapters"]}
        topic_ids = {(t["chapter_id"], t["name"]): t["id"] for t in tax["topics"]}
        ocr_pages = set(content.ocr_pages)
        inserted: list[tuple[dict, dict]] = []
        classified = errors = already = 0
        for pq in questions:
            subject = pq.subject_hint
            multi_subject_numbering = len({q.subject_hint for q in questions if q.subject_hint}) > 1 and len({q.number for q in questions}) < len(questions)
            oid = f"{exam_code}-{doc['exam_year']}-{doc.get('session') or 'x'}-{doc.get('shift') or 'x'}-P{doc.get('paper_number') or 1}-" + (f"{(subject or 'x')[:3]}-" if multi_subject_numbering else "") + f"Q{pq.number}"
            if self.s.question_by_original_id(paper["id"], oid):
                already += 1
                continue
            fp = fingerprint(pq.statement, pq.options)
            other = self.s.question_by_fingerprint(fp)
            if other:
                self.stats.add("duplicates_skipped")
                self.log("warn", f"Q{pq.number} duplicates an existing question ({other['id'][:8]}); not imported", {"stage": "dedupe", "question_id": other["id"]}, doc)
                continue
            cls = None
            if self.classify_fn and errors < 5:
                try:
                    allowed = {subject: tax["by_subject"].get(subject, [])} if subject else tax["by_subject"]
                    cls = self.classify_fn(pq.statement + (" " + " ".join(o["content"] for o in pq.options) if pq.options else ""), allowed)
                    self._sleep(self.cfg.classify_delay)
                except Exception as e:
                    errors += 1
                    self.log("warn", f"Q{pq.number}: AI classification failed ({type(e).__name__}: {e})", {"stage": "classify"}, doc)
            if subject is None and cls and cls.get("subject") in code_to_id:
                subject = cls["subject"]
            if subject not in code_to_id:
                self.log("warn", f"Q{pq.number} skipped: its subject could not be determined (no Physics/Chemistry/Mathematics heading above it and no AI classification)", {"stage": "extract"}, doc)
                continue
            sid = code_to_id[subject]
            chap = None
            if cls and cls.get("subject") in (None, subject):
                chap = chapter_ids.get((sid, cls.get("chapter")))
            topic = topic_ids.get((chap, cls.get("topic"))) if cls and chap else None
            warnings = list(pq.warnings)
            if cls and cls.get("subject") not in (None, subject):
                warnings.append(f"ai_subject_disagrees:{cls.get('subject')}")
            if cls and not chap:
                warnings.append("ai_chapter_not_in_taxonomy")
            conf = cls["confidence"] if cls else None
            row = {"paper_id": paper["id"], "original_question_id": oid, "question_number": pq.number, "subject_id": sid, "chapter_id": chap, "topic_id": topic,
                   "difficulty": cls.get("difficulty") if cls else None, "difficulty_is_estimated": True, "question_type": pq.question_type, "statement": pq.statement,
                   "classification_source": "ai" if cls else "import", "classification_confidence": conf, "needs_review": True, "answer_verified": False,
                   "source_status": "awaiting_verification", "answer_source": "awaiting_verification", "source_document_id": doc["id"], "source_page": pq.page_start,
                   "source_page_end": pq.page_end, "content_fingerprint": fp, "is_published": False,
                   "extraction_flags": {"ocr": pq.ocr, "math_heavy": pq.flags["math_heavy"], "mentions_figure": pq.flags["mentions_figure"], "paragraph": pq.flags["paragraph"], "warnings": warnings}}
            q = self.s.insert_question(row, pq.options, exam_id=doc["exam_id"])
            inserted.append((q, {"pq": pq, "subject_id": sid}))
            self.stats.add("questions_extracted")
            self.stats.add("questions_requiring_review")
            if chap:
                classified += 1
                self.stats.add("questions_classified")
            pool = self.s.statement_pool(doc["exam_id"], sid)
            for qid, sim in near_duplicates(pq.statement, [p for p in pool if p[0] != q["id"]])[:3]:
                self.s.add_duplicate_candidate(q["id"], qid, sim)
                self.log("warn", f"Q{pq.number} is {sim:.0%} similar to question {qid[:8]}; flagged as a possible duplicate", {"stage": "dedupe"}, doc)
        self._attach_images(doc, paper, inserted, ocr_pages, pdf_path)
        n_new = len(inserted)
        self.s.update_job(job["id"], {"questions_extracted": n_new, "questions_classified": classified, "questions_needing_review": n_new})
        self.log("info", f"{n_new} question(s) stored, {already} already present, {classified} classified by AI", {"stage": "extract"}, doc)
        if n_new == 0 and already == 0:
            return self.set_status(doc, "failed", "no_questions_stored: questions were parsed but none could be stored (see the log for each one)", job)
        self.set_status(doc, "extracted", f"{n_new} question(s) stored for review", job)
        if self.classify_fn is None:
            return self.s.update_document(doc["id"], {"status_reason": f"{n_new} question(s) stored with subject only: AI provider not configured, so chapter and difficulty are blank. Set the provider secret and retry, or classify in Admin."})
        if n_new and classified < n_new:
            self.s.update_document(doc["id"], {"status_reason": f"{n_new - classified} of {n_new} question(s) have no AI chapter; classify them in Admin."})
        self.set_status(doc, "classified", doc.get("status_reason"), job)
        self.set_status(doc, "awaiting_review", "questions are unverified and unpublished; review them in Admin", job)

    def _attach_images(self, doc, paper, inserted, ocr_pages, pdf_path):
        if not inserted:
            return
        try:
            items = [{"number": m["pq"].number, "pieces": m["pq"].pieces,
                      "needs_snapshot": m["pq"].ocr or m["pq"].flags["math_heavy"] or m["pq"].flags["mentions_figure"] or bool(m["pq"].warnings)} for _, m in inserted]
            got = figures.collect(pdf_path, items, ocr_pages)
        except Exception as e:
            self.log("warn", f"Figures could not be extracted ({type(e).__name__}: {e}); questions are stored without images", {"stage": "figures"}, doc)
            return
        for idx, imgs in got.items():
            q = inserted[idx][0]
            meta = []
            for k, im in enumerate(imgs):
                p = f"papers/{paper['id']}/{q['id']}-{im['kind']}{k}.png"
                try:
                    self.s.put_image(p, im["png"])
                    meta.append({"bucket": "question-images", "path": p, "kind": im["kind"], "page": im["page"]})
                except Exception as e:
                    self.log("warn", f"Image upload failed for Q{inserted[idx][1]['pq'].number}: {e}", {"stage": "figures"}, doc)
            if meta:
                self.s.update_question(q["id"], {"images": meta})

    # ------------------------------------------------------------------ 4. matching
    def match_all(self):
        keys = [d for d in self.s.documents_with_status(["extracted", "awaiting_review", "completed"], ["answer_key"])]
        for d in keys:
            entries = self.s.list_entries(d["id"])
            if not entries:
                continue
            papers = self.s.list_papers(d["exam_id"])
            pm = match_paper(d, papers)
            qs = self.s.questions_for_matching(pm.paper["id"]) if pm.paper else []
            for eid, upd in match_entries(d, entries, pm, qs).items():
                self.s.update_entry(eid, upd)
            self.log("info", f"Key {_name(d)}: paper match = {pm.status}" + (f" ({pm.note})" if pm.note else ""), {"stage": "match", "paper": pm.paper["id"] if pm.paper else None}, d)
        # Different key documents (provisional vs final) must not silently disagree.
        docs = {d["id"]: d for d in self.s.all_documents() if d["doc_kind"] == "answer_key"}
        rows = [e for e in self.s.list_entries(statuses=["proposed"])]
        for eid, upd in reconcile_across_documents(rows, docs).items():
            self.s.update_entry(eid, upd)
        # Count what is waiting (this run's view of all entries).
        allrows = self.s.list_entries()
        for status, key in (("proposed", "answer_entries_proposed"), ("ambiguous", "answer_entries_ambiguous"), ("unmatched", "answer_entries_unmatched")):
            self.stats[key] = sum(1 for e in allrows if e["match_status"] == status)

    def refresh_completion(self):
        """Moves documents to `completed` only when a person has finished with them."""
        for d in self.s.documents_with_status(["awaiting_review", "extracted"], ["answer_key"]):
            es = self.s.list_entries(d["id"])
            if not es:
                continue
            if all(e["match_status"] in ("confirmed", "rejected") for e in es):
                self.set_status(d, "completed", "every entry confirmed or rejected")
            elif d["import_status"] == "extracted":
                self.set_status(d, "awaiting_review", f"{sum(1 for e in es if e['match_status'] in ('confirmed','rejected'))}/{len(es)} entries reviewed")
        for d in self.s.documents_with_status(["awaiting_review"], ["question_paper"]):
            p = next((p for p in self.s.list_papers(d["exam_id"]) if p.get("source_document_id") == d["id"]), None)
            if p and self.s.paper_published(p["id"]):
                self.set_status(d, "completed", "paper published")


def _name(doc: dict) -> str:
    from sources.metadata import file_stem
    return file_stem(doc.get("source_url") or doc.get("storage_path") or doc["id"])[:60]


def _paper_name(p: dict) -> str:
    return f"{p['exam_year']} session={p.get('session')} shift={p.get('shift')} paper={p.get('paper_number')}"
