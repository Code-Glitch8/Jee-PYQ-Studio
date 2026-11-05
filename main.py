"""Import runner, executed by GitHub Actions with SUPABASE_SERVICE_ROLE_KEY from GitHub Secrets.

Flow: honour pause flag -> claim/create run -> discover official PDFs -> download + hash -> store in Supabase Storage ->
extract (OCR when scanned) -> classify with AI when configured -> insert as unverified for admin review.
Nothing is invented: if a step cannot run (no AI key, no text), the job is marked skipped or failed with the reason.
"""
import hashlib, os, re, sys, tempfile
from datetime import datetime, timezone
from supabase import create_client
from sources.official import discover, polite_get, allowed
from extraction.pdf_text import extract_text, split_questions, parse_answer_key
from classification.classifier import classify, configured

db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
RUN = None
now = lambda: datetime.now(timezone.utc).isoformat()

def log(level, message, details=None, doc=None):
    print(f"[{level}] {message}")
    db.table("import_logs").insert({"run_id": RUN, "document_id": doc, "level": level, "message": message, "details": details or {}}).execute()

def setting(key, default=None):
    r = db.table("app_settings").select("value").eq("key", key).execute().data
    return r[0]["value"] if r else default

def taxonomy():
    ch = db.table("chapters").select("id,name,subject_id").execute().data
    subj = {s["id"]: s for s in db.table("subjects").select("*").execute().data}
    tx = {}
    for c in ch: tx.setdefault(subj[c["subject_id"]]["code"], []).append(c["name"])
    return tx, ch, subj

def register(doc, exam_ids):
    r = polite_get(doc["url"])
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        return log("warn", f"Not a downloadable PDF: {doc['url']} ({r.status_code})")
    sha = hashlib.sha256(r.content).hexdigest()
    if db.table("source_documents").select("id").eq("sha256", sha).execute().data:
        return  # already imported
    path = f"{doc['exam']}/{sha[:16]}.pdf"
    db.storage.from_("source-documents").upload(path, r.content, {"content-type": "application/pdf", "upsert": "true"})
    row = db.table("source_documents").insert({"exam_id": exam_ids[doc["exam"]], "doc_kind": doc["doc_kind"], "source_url": doc["url"], "source_page_url": doc["page"],
        "storage_path": path, "sha256": sha, "status": "official", "origin": "official_site", "exam_year": doc["exam_year"], "session": doc["session"], "shift": doc["shift"]}).execute().data[0]
    db.table("import_jobs").insert({"run_id": RUN, "document_id": row["id"], "status": "pending"}).execute()
    log("info", f"Registered {doc['doc_kind']} {doc['url']}", doc=row["id"])

def process(job, tx, chapters, subj):
    d = db.table("source_documents").select("*").eq("id", job["document_id"]).single().execute().data
    blob = db.storage.from_("source-documents").download(d["storage_path"])
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(blob); f.flush(); text, ocr = extract_text(f.name)
    if len(text.strip()) < 200:
        raise RuntimeError("No usable text found (OCR may be missing). Upload a cleaner copy manually.")
    if d["doc_kind"] == "answer_key":
        key = parse_answer_key(text)
        log("info", f"Parsed {len(key)} answer-key rows; stored for matching, not applied automatically", {"rows": len(key)}, d["id"])
        return len(key), "skipped"
    provider = os.environ.get("AI_PROVIDER", "gemini")
    if not configured(provider):
        raise RuntimeError(f"AI provider '{provider}' is not configured, so questions cannot be classified. Set its secret and retry.")
    if not d["exam_year"]:
        raise RuntimeError("Exam year could not be read from the link. Set it on the document in Admin, then retry.")
    paper = db.table("papers").upsert({"exam_id": d["exam_id"], "exam_year": d["exam_year"], "session": d["session"], "shift": d["shift"], "paper_number": d["paper_number"],
        "source_url": d["source_url"], "source_document_id": d["id"], "source_status": "official", "is_published": False}, on_conflict="exam_id,exam_year,session,paper_number,shift").execute().data[0]
    code_to_id = {s["code"]: s["id"] for s in subj.values()}
    n = 0
    for q in split_questions(text):
        fp = hashlib.sha256(re.sub(r"\W+", "", q["statement"].lower()).encode()).hexdigest()
        if db.table("questions").select("id").eq("content_fingerprint", fp).execute().data:
            continue  # duplicate by content
        c = classify(provider, q["statement"], tx)
        if not c or c.get("subject") not in code_to_id:
            log("warn", f"Q{q['number']} could not be classified; skipped", doc=d["id"]); continue
        chap = next((x for x in chapters if x["name"] == c.get("chapter") and x["subject_id"] == code_to_id[c["subject"]]), None)
        qtype = "single_mcq" if len(q["options"]) >= 2 else "numerical"
        row = db.table("questions").insert({"paper_id": paper["id"], "original_question_id": f"{d['sha256'][:8]}-Q{q['number']}", "question_number": q["number"],
            "subject_id": code_to_id[c["subject"]], "chapter_id": chap["id"] if chap else None, "difficulty": c.get("difficulty"), "difficulty_is_estimated": True,
            "question_type": qtype, "statement": q["statement"], "classification_source": "ai", "classification_confidence": c["confidence"],
            "needs_review": True, "answer_verified": False, "source_status": "awaiting_verification",
            "source_document_id": d["id"], "content_fingerprint": fp, "is_published": False}).execute().data[0]
        if q["options"]:
            db.table("question_options").insert([{"question_id": row["id"], "label": o["label"], "content": o["content"], "sort_order": i} for i, o in enumerate(q["options"])]).execute()
        n += 1
    return n, "done"

def main():
    global RUN
    if setting("import_paused", False):
        print("Imports are paused in Admin settings."); return
    queued = db.table("import_runs").select("id").eq("status", "queued").order("created_at").limit(1).execute().data
    trigger = "manual" if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" else "schedule"
    RUN = queued[0]["id"] if queued else db.table("import_runs").insert({"trigger": trigger, "status": "running"}).execute().data[0]["id"]
    db.table("import_runs").update({"status": "running", "started_at": now()}).eq("id", RUN).execute()
    try:
        exam_ids = {e["code"]: e["id"] for e in db.table("exams").select("*").execute().data}
        for doc in discover(lambda l, m, d: log(l, m, d)):
            if allowed(doc["url"]): register(doc, exam_ids)
        tx, chapters, subj = taxonomy()
        for job in db.table("import_jobs").select("*").eq("status", "pending").execute().data:
            if setting("import_paused", False): log("info", "Paused mid-run"); break
            db.table("import_jobs").update({"status": "running", "attempts": job["attempts"] + 1, "updated_at": now()}).eq("id", job["id"]).execute()
            try:
                count, st = process(job, tx, chapters, subj)
                db.table("import_jobs").update({"status": st, "questions_extracted": count, "last_error": None, "updated_at": now()}).eq("id", job["id"]).execute()
            except Exception as e:  # keep going; the failure is visible in Admin
                db.table("import_jobs").update({"status": "failed", "last_error": str(e)[:500], "updated_at": now()}).eq("id", job["id"]).execute()
                log("error", str(e)[:500], doc=job["document_id"])
        db.table("import_runs").update({"status": "completed", "finished_at": now()}).eq("id", RUN).execute()
    except Exception as e:
        log("error", f"Run failed: {e}")
        db.table("import_runs").update({"status": "failed", "finished_at": now()}).eq("id", RUN).execute()
        sys.exit(1)

if __name__ == "__main__":
    main()
