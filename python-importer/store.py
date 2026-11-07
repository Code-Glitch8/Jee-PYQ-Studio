"""Data access for the importer. `SupabaseStore` talks to the real project (service-role key, CI only);
`MemoryStore` has the same interface in memory so the whole pipeline can be tested without a database."""
from __future__ import annotations
import copy
import uuid
from datetime import datetime, timezone


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, settings: dict | None = None):
        self.settings = {"import_paused": False, **(settings or {})}
        self.exam_ids = {"jee_main": 3, "jee_advanced": 4}
        self.subjects = {1: {"id": 1, "code": "physics"}, 2: {"id": 2, "code": "chemistry"}, 3: {"id": 3, "code": "mathematics"}}
        self.chapters = [{"id": 10, "name": "Kinematics", "subject_id": 1}, {"id": 11, "name": "Work, Energy and Power", "subject_id": 1},
                         {"id": 20, "name": "Thermodynamics", "subject_id": 2}, {"id": 30, "name": "Quadratic Equations", "subject_id": 3}]
        self.topics: list[dict] = []
        self.runs: dict[str, dict] = {}
        self.logs: list[dict] = []
        self.documents: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self.sources: dict[str, bytes] = {}
        self.images: dict[str, bytes] = {}
        self.papers: dict[str, dict] = {}
        self.questions: dict[str, dict] = {}
        self.options: dict[str, list[dict]] = {}
        self.entries: dict[str, dict] = {}
        self.duplicates: list[dict] = []

    # settings / reference
    def setting(self, key, default=None):
        return self.settings.get(key, default)

    def exams(self):
        return dict(self.exam_ids)

    def taxonomy(self):
        tx: dict[str, list[str]] = {}
        for c in self.chapters:
            tx.setdefault(self.subjects[c["subject_id"]]["code"], []).append(c["name"])
        return {"by_subject": tx, "chapters": self.chapters, "subjects": self.subjects, "topics": self.topics}

    # runs / logs
    def claim_run(self, trigger: str, mode: str, only_if_queued: bool):
        queued = sorted((r for r in self.runs.values() if r["status"] == "queued"), key=lambda r: r["created_at"])
        if queued:
            r = queued[0]
            r.update(status="running", started_at=now())
            return r
        if only_if_queued:
            return None
        rid = str(uuid.uuid4())
        self.runs[rid] = {"id": rid, "trigger": trigger, "mode": mode, "status": "running", "started_at": now(), "created_at": now(), "stats": {}}
        return self.runs[rid]

    def finish_run(self, run_id, status, stats):
        self.runs[run_id].update(status=status, finished_at=now(), stats=stats)

    def log(self, run_id, level, message, details=None, document_id=None):
        self.logs.append({"run_id": run_id, "document_id": document_id, "level": level, "message": message, "details": details or {}, "created_at": now()})

    # documents
    def get_document(self, doc_id):
        return copy.deepcopy(self.documents.get(doc_id))

    def get_document_by_url(self, url):
        return next((copy.deepcopy(d) for d in self.documents.values() if d.get("source_url") == url), None)

    def find_by_sha(self, sha):
        return next((copy.deepcopy(d) for d in self.documents.values() if d.get("sha256") == sha), None)

    def insert_document(self, fields):
        did = str(uuid.uuid4())
        row = {"id": did, "status": "official", "origin": "official_site", "import_status": "discovered", "detected": {}, "ocr_used": False,
               "storage_path": None, "sha256": None, "discovered_at": now(), **fields}
        self.documents[did] = row
        return copy.deepcopy(row)

    def update_document(self, doc_id, fields):
        self.documents[doc_id].update(fields, updated_at=now())

    def documents_with_status(self, statuses, kinds=None):
        return [copy.deepcopy(d) for d in self.documents.values() if d["import_status"] in statuses and (kinds is None or d["doc_kind"] in kinds)]

    def all_documents(self):
        return [copy.deepcopy(d) for d in self.documents.values()]

    # jobs
    def ensure_job(self, doc_id, run_id):
        j = next((j for j in self.jobs.values() if j["document_id"] == doc_id), None)
        if j is None:
            jid = str(uuid.uuid4())
            j = self.jobs[jid] = {"id": jid, "document_id": doc_id, "run_id": run_id, "status": "pending", "attempts": 0, "questions_extracted": 0,
                                  "questions_classified": 0, "questions_needing_review": 0, "answer_rows": 0, "last_error": None}
        return copy.deepcopy(j)

    def update_job(self, job_id, fields):
        self.jobs[job_id].update(fields, updated_at=now())

    def pending_jobs(self, document_id=None, only_failed=False):
        return [copy.deepcopy(j) for j in self.jobs.values() if j["status"] == "pending" and (document_id is None or j["document_id"] == document_id)]

    # storage
    def put_source(self, path, data):
        self.sources[path] = data

    def get_source(self, path):
        return self.sources[path]

    def put_image(self, path, data):
        self.images[path] = data

    # papers / questions
    def list_papers(self, exam_id=None):
        return [copy.deepcopy(p) for p in self.papers.values() if exam_id is None or p["exam_id"] == exam_id]

    def find_or_create_paper(self, fields):
        key = ("exam_id", "exam_year", "session", "paper_number", "shift")
        for p in self.papers.values():
            if all(p.get(k) == fields.get(k) for k in key):
                if not p.get("source_document_id"):
                    p["source_document_id"] = fields.get("source_document_id")
                return copy.deepcopy(p), False
        pid = str(uuid.uuid4())
        self.papers[pid] = {"id": pid, "is_published": False, "answer_key_document_id": None, **fields}
        return copy.deepcopy(self.papers[pid]), True

    def question_by_original_id(self, paper_id, original_id):
        return next((copy.deepcopy(q) for q in self.questions.values() if q["paper_id"] == paper_id and q["original_question_id"] == original_id), None)

    def question_by_fingerprint(self, fp):
        return next((copy.deepcopy(q) for q in self.questions.values() if q["content_fingerprint"] == fp), None)

    def statement_pool(self, exam_id, subject_id):
        return [(q["id"], q["statement"]) for q in self.questions.values() if q.get("_exam_id") == exam_id and q["subject_id"] == subject_id]

    def insert_question(self, row, options, exam_id=None):
        qid = str(uuid.uuid4())
        self.questions[qid] = {"id": qid, "_exam_id": exam_id, **row}
        self.options[qid] = list(options)
        return copy.deepcopy(self.questions[qid])

    def update_question(self, qid, fields):
        self.questions[qid].update(fields)

    def add_duplicate_candidate(self, a, b, sim):
        self.duplicates.append({"question_a": a, "question_b": b, "similarity": sim})

    def questions_for_matching(self, paper_id):
        out = []
        for q in self.questions.values():
            if q["paper_id"] == paper_id:
                out.append({"id": q["id"], "question_number": q["question_number"], "question_type": q["question_type"],
                            "subject_code": self.subjects[q["subject_id"]]["code"], "option_labels": [o["label"] for o in self.options.get(q["id"], [])]})
        return out

    def paper_question_stats(self, paper_id):
        qs = [q for q in self.questions.values() if q["paper_id"] == paper_id]
        return {"total": len(qs), "published": sum(1 for q in qs if q.get("is_published"))}

    # answer-key entries
    def replace_entries(self, doc_id, entries):
        keep = {(e["subject_code"], e["question_number"], e["original_question_id"]) for e in self.entries.values()
                if e["source_document_id"] == doc_id and e["match_status"] in ("confirmed", "rejected")}
        for eid in [i for i, e in self.entries.items() if e["source_document_id"] == doc_id and e["match_status"] not in ("confirmed", "rejected")]:
            del self.entries[eid]
        n = 0
        for e in entries:
            if (e.get("subject_code"), e.get("question_number"), e.get("original_question_id")) in keep:
                continue
            eid = str(uuid.uuid4())
            self.entries[eid] = {"id": eid, "source_document_id": doc_id, "match_status": "unmatched", "matched_question_id": None, "paper_id": None,
                                 "candidate_question_ids": [], "match_note": None, "original_question_id": None, "subject_code": None, **e}
            n += 1
        return n

    def list_entries(self, document_id=None, statuses=None):
        return [copy.deepcopy(e) for e in self.entries.values() if (document_id is None or e["source_document_id"] == document_id)
                and (statuses is None or e["match_status"] in statuses)]

    def update_entry(self, entry_id, fields):
        self.entries[entry_id].update(fields)

    def snapshot_counts(self):
        out: dict[str, int] = {}
        for d in self.documents.values():
            out[d["import_status"]] = out.get(d["import_status"], 0) + 1
        return out

    def paper_published(self, paper_id):
        return bool(self.papers.get(paper_id, {}).get("is_published"))


class SupabaseStore(MemoryStore):
    """Same interface, backed by Supabase. Inherits nothing but the signature (every method is overridden)."""

    def __init__(self, url: str, key: str):
        from supabase import create_client
        self.db = create_client(url, key)

    # ---- helpers
    def _all(self, table, select="*", **eq):
        out, start = [], 0
        while True:
            q = self.db.table(table).select(select)
            for k, v in eq.items():
                q = q.eq(k, v)
            chunk = q.range(start, start + 999).execute().data
            out += chunk
            if len(chunk) < 1000:
                return out
            start += 1000

    def setting(self, key, default=None):
        r = self.db.table("app_settings").select("value").eq("key", key).execute().data
        return r[0]["value"] if r else default

    def exams(self):
        return {e["code"]: e["id"] for e in self.db.table("exams").select("id,code").execute().data}

    def taxonomy(self):
        subjects = {s["id"]: s for s in self.db.table("subjects").select("id,code").execute().data}
        chapters = self._all("chapters", "id,name,subject_id")
        topics = self._all("topics", "id,name,chapter_id")
        by: dict[str, list[str]] = {}
        for c in chapters:
            by.setdefault(subjects[c["subject_id"]]["code"], []).append(c["name"])
        return {"by_subject": by, "chapters": chapters, "subjects": subjects, "topics": topics}

    def claim_run(self, trigger, mode, only_if_queued):
        q = self.db.table("import_runs").select("*").eq("status", "queued").order("created_at").limit(1).execute().data
        if q:
            self.db.table("import_runs").update({"status": "running", "started_at": now()}).eq("id", q[0]["id"]).execute()
            return {**q[0], "status": "running"}
        if only_if_queued:
            return None
        return self.db.table("import_runs").insert({"trigger": trigger, "mode": mode, "status": "running", "started_at": now()}).execute().data[0]

    def finish_run(self, run_id, status, stats):
        self.db.table("import_runs").update({"status": status, "finished_at": now(), "stats": stats}).eq("id", run_id).execute()

    def log(self, run_id, level, message, details=None, document_id=None):
        try:
            self.db.table("import_logs").insert({"run_id": run_id, "document_id": document_id, "level": level, "message": message[:2000], "details": details or {}}).execute()
        except Exception as e:     # logging must never take the run down
            print(f"[log-failed] {e}")

    def get_document(self, doc_id):
        r = self.db.table("source_documents").select("*").eq("id", doc_id).execute().data
        return r[0] if r else None

    def get_document_by_url(self, url):
        r = self.db.table("source_documents").select("*").eq("source_url", url).execute().data
        return r[0] if r else None

    def find_by_sha(self, sha):
        r = self.db.table("source_documents").select("*").eq("sha256", sha).execute().data
        return r[0] if r else None

    def insert_document(self, fields):
        return self.db.table("source_documents").insert(_jsonable(fields)).execute().data[0]

    def update_document(self, doc_id, fields):
        self.db.table("source_documents").update(_jsonable(fields)).eq("id", doc_id).execute()

    def documents_with_status(self, statuses, kinds=None):
        q = self.db.table("source_documents").select("*").in_("import_status", list(statuses))
        if kinds:
            q = q.in_("doc_kind", list(kinds))
        return q.execute().data

    def all_documents(self):
        return self._all("source_documents")

    def ensure_job(self, doc_id, run_id):
        r = self.db.table("import_jobs").select("*").eq("document_id", doc_id).limit(1).execute().data
        if r:
            return r[0]
        return self.db.table("import_jobs").insert({"document_id": doc_id, "run_id": run_id, "status": "pending"}).execute().data[0]

    def update_job(self, job_id, fields):
        self.db.table("import_jobs").update({**fields, "updated_at": now()}).eq("id", job_id).execute()

    def pending_jobs(self, document_id=None, only_failed=False):
        q = self.db.table("import_jobs").select("*").eq("status", "pending")
        if document_id:
            q = q.eq("document_id", document_id)
        return q.execute().data

    def put_source(self, path, data):
        self.db.storage.from_("source-documents").upload(path, data, {"content-type": "application/pdf", "upsert": "true"})

    def get_source(self, path):
        return self.db.storage.from_("source-documents").download(path)

    def put_image(self, path, data):
        self.db.storage.from_("question-images").upload(path, data, {"content-type": "image/png", "upsert": "true"})

    def list_papers(self, exam_id=None):
        q = self.db.table("papers").select("*")
        if exam_id is not None:
            q = q.eq("exam_id", exam_id)
        return q.execute().data

    def find_or_create_paper(self, fields):
        q = self.db.table("papers").select("*")
        for k in ("exam_id", "exam_year", "paper_number"):
            q = q.eq(k, fields[k])
        for k in ("session", "shift"):
            q = q.is_(k, "null") if fields.get(k) is None else q.eq(k, fields[k])
        r = q.limit(1).execute().data
        if r:
            if not r[0].get("source_document_id") and fields.get("source_document_id"):
                self.db.table("papers").update({"source_document_id": fields["source_document_id"]}).eq("id", r[0]["id"]).execute()
            return r[0], False
        return self.db.table("papers").insert(_jsonable(fields)).execute().data[0], True

    def question_by_original_id(self, paper_id, original_id):
        r = self.db.table("questions").select("id,content_fingerprint").eq("paper_id", paper_id).eq("original_question_id", original_id).execute().data
        return r[0] if r else None

    def question_by_fingerprint(self, fp):
        r = self.db.table("questions").select("id,paper_id").eq("content_fingerprint", fp).execute().data
        return r[0] if r else None

    def statement_pool(self, exam_id, subject_id):
        rows = self.db.table("questions").select("id,statement,papers!inner(exam_id)").eq("subject_id", subject_id).eq("papers.exam_id", exam_id).limit(5000).execute().data
        return [(r["id"], r["statement"]) for r in rows]

    def insert_question(self, row, options, exam_id=None):
        q = self.db.table("questions").insert(_jsonable(row)).execute().data[0]
        if options:
            self.db.table("question_options").insert([{"question_id": q["id"], "label": o["label"], "content": o["content"], "sort_order": i} for i, o in enumerate(options)]).execute()
        return q

    def update_question(self, qid, fields):
        self.db.table("questions").update(_jsonable(fields)).eq("id", qid).execute()

    def add_duplicate_candidate(self, a, b, sim):
        self.db.table("duplicate_candidates").upsert({"question_a": a, "question_b": b, "similarity": round(sim, 3)}, on_conflict="question_a,question_b").execute()

    def questions_for_matching(self, paper_id):
        qs = self.db.table("questions").select("id,question_number,question_type,subjects(code),question_options(label)").eq("paper_id", paper_id).execute().data
        return [{"id": q["id"], "question_number": q["question_number"], "question_type": q["question_type"], "subject_code": (q.get("subjects") or {}).get("code"),
                 "option_labels": [o["label"] for o in q.get("question_options") or []]} for q in qs]

    def replace_entries(self, doc_id, entries):
        existing = self._all("answer_key_entries", "id,subject_code,question_number,original_question_id,match_status", source_document_id=doc_id)
        keep = {(e["subject_code"], e["question_number"], e["original_question_id"]) for e in existing if e["match_status"] in ("confirmed", "rejected")}
        drop = [e["id"] for e in existing if e["match_status"] not in ("confirmed", "rejected")]
        for i in range(0, len(drop), 100):
            self.db.table("answer_key_entries").delete().in_("id", drop[i:i + 100]).execute()
        rows = [{**_jsonable(e), "source_document_id": doc_id} for e in entries if (e.get("subject_code"), e.get("question_number"), e.get("original_question_id")) not in keep]
        for i in range(0, len(rows), 200):
            self.db.table("answer_key_entries").insert(rows[i:i + 200]).execute()
        return len(rows)

    def list_entries(self, document_id=None, statuses=None):
        q = self.db.table("answer_key_entries").select("*")
        if document_id:
            q = q.eq("source_document_id", document_id)
        if statuses:
            q = q.in_("match_status", list(statuses))
        return q.limit(5000).execute().data

    def update_entry(self, entry_id, fields):
        self.db.table("answer_key_entries").update(_jsonable(fields)).eq("id", entry_id).execute()

    def snapshot_counts(self):
        out: dict[str, int] = {}
        for d in self._all("source_documents", "import_status"):
            out[d["import_status"]] = out.get(d["import_status"], 0) + 1
        return out

    def paper_published(self, paper_id):
        r = self.db.table("papers").select("is_published").eq("id", paper_id).execute().data
        return bool(r and r[0]["is_published"])


def _jsonable(d: dict) -> dict:
    import datetime as dt
    return {k: (v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v) for k, v in d.items()}
