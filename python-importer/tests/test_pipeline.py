"""End-to-end runs against an in-memory store and a fake website. No network, no database."""
import pytest

from pipeline import Config, Pipeline
from sources.crawler import Seed
from report import Stats, outcome
from store import MemoryStore
from tests.conftest import FakeSite, KEY_PAGE, PAPER_PAGE1, PAPER_PAGE2, make_pdf

H = "https://jeeadv.ac.in"
QP = H + "/past/JEE_Main_2023_Session_1_Shift_2_Question_Paper.pdf"
KEYURL = H + "/past/JEE_Main_2023_Session_1_Shift_2_Final_Answer_Key.pdf"


def pdf_bytes(tmp_path, name, pages, **kw):
    return open(make_pdf(tmp_path / name, pages, **kw), "rb").read()


def archive(*links):
    return '<html><title>Previous Year Question Papers</title><body>' + "".join(f'<a href="{u}">{t}</a>' for u, t in links) + "</body></html>"


SEEDS = [Seed("jee_advanced", H + "/", "jeeadv.ac.in")]


def build(tmp_path, extra=None, classify=None, store=None, cfg=None):
    pages = {H + "/": (200, "text/html", archive(("/archive.html", "Previous year papers"))),
             H + "/archive.html": (200, "text/html", archive((QP, "Question Paper"), (KEYURL, "Final Answer Key"))),
             QP: (200, "application/pdf", pdf_bytes(tmp_path, "qp.pdf", [PAPER_PAGE1, PAPER_PAGE2], header="NTA JEE Main", footer_numbers=True)),
             KEYURL: (200, "application/pdf", pdf_bytes(tmp_path, "key.pdf", [KEY_PAGE]))}
    pages.update(extra or {})
    site = FakeSite(pages)
    st = store or MemoryStore()
    p = Pipeline(st, site, classify, cfg or Config(delay=0, classify_delay=0), sleep=lambda s: None, seeds=SEEDS)
    return p, st, site


def run(tmp_path, **kw):
    p, st, site = build(tmp_path, **kw)
    p.run()
    return p, st, site


def docs(st):
    return {d["source_url"].rsplit("/", 1)[-1]: d for d in st.documents.values()}


def test_full_run_statuses_and_counters(tmp_path):
    p, st, _ = run(tmp_path)
    d = docs(st)
    qp, key = d["JEE_Main_2023_Session_1_Shift_2_Question_Paper.pdf"], d["JEE_Main_2023_Session_1_Shift_2_Final_Answer_Key.pdf"]
    # question paper: stored, subject from headings, no AI configured -> stays at "extracted" with an honest reason
    assert qp["import_status"] == "extracted" and "AI provider not configured" in qp["status_reason"]
    assert key["import_status"] == "awaiting_review"                      # a key never reaches "completed" by itself
    s = p.stats
    assert (s["pdfs_discovered"], s["question_papers_downloaded"], s["answer_keys_downloaded"]) == (2, 1, 1)
    assert s["questions_extracted"] == 6 and s["questions_classified"] == 0 and s["questions_requiring_review"] == 6
    assert s["answer_entries_extracted"] == 8 and s["documents_failed"] == 0


def test_answer_key_processing_does_not_make_the_paper_look_imported(tmp_path):
    # only the key is available: the run must not report any imported questions
    p, st, _ = run(tmp_path, extra={QP: (404, "text/html", "gone")})
    d = docs(st)
    assert d["JEE_Main_2023_Session_1_Shift_2_Question_Paper.pdf"]["import_status"] == "failed"
    assert p.stats["questions_extracted"] == 0 and p.stats["answer_keys_downloaded"] == 1 and p.stats["question_papers_downloaded"] == 0
    assert all(e["match_status"] == "unmatched" and "no question paper" in e["match_note"] for e in st.entries.values())


def test_questions_extracted_correctly_and_unverified(tmp_path):
    _, st, _ = run(tmp_path)
    qs = sorted(st.questions.values(), key=lambda q: q["question_number"])
    assert [q["question_number"] for q in qs] == [1, 2, 3, 4, 5, 6]
    assert all(not q["is_published"] and not q["answer_verified"] and q["needs_review"] for q in qs)
    assert [q["question_type"] for q in qs] == ["single_mcq", "single_mcq", "single_mcq", "integer", "integer", "single_mcq"]
    assert qs[0]["classification_source"] == "import" and qs[0]["difficulty"] is None
    assert {st.subjects[q["subject_id"]]["code"] for q in qs} == {"physics", "chemistry"}
    assert "correct_answer" not in qs[0] or qs[0].get("correct_answer") is None


def test_answers_are_proposed_for_confirmation_never_written_to_questions(tmp_path):
    _, st, _ = run(tmp_path)
    proposed = [e for e in st.entries.values() if e["match_status"] == "proposed"]
    assert proposed, "unambiguous entries should be proposed"
    assert all(q.get("correct_answer") is None and q.get("answer_verified") is False for q in st.questions.values())
    by = {(e["subject_code"], e["question_number"]): e for e in st.entries.values()}
    q1 = next(q for q in st.questions.values() if q["question_number"] == 1)
    assert by[("physics", 1)]["matched_question_id"] == q1["id"] and by[("physics", 1)]["answer"] == ["C"]
    q4 = next(q for q in st.questions.values() if q["question_number"] == 4)
    assert by[("physics", 4)]["answer"] == 2 and by[("physics", 4)]["matched_question_id"] == q4["id"]


def test_entries_for_questions_that_were_not_extracted_stay_unmatched(tmp_path):
    _, st, _ = run(tmp_path)
    e = next(e for e in st.entries.values() if e["subject_code"] == "chemistry" and e["question_number"] == 7)
    assert e["match_status"] == "unmatched" and "was not extracted" in e["match_note"]


def test_classified_with_ai_moves_through_classified_to_awaiting_review(tmp_path):
    calls = []
    def ai(statement, taxonomy):
        calls.append(taxonomy)
        subj = next(iter(taxonomy))
        return {"subject": subj, "chapter": taxonomy[subj][0], "topic": None, "difficulty": "easy", "confidence": 0.9}
    p, st, _ = run(tmp_path, classify=ai)
    qp = docs(st)["JEE_Main_2023_Session_1_Shift_2_Question_Paper.pdf"]
    assert qp["import_status"] == "awaiting_review" and p.stats["questions_classified"] == 6
    assert all(len(t) == 1 for t in calls)                          # the AI only sees the subject printed in the paper
    statuses = [l["details"].get("status") for l in st.logs if l["document_id"] == qp["id"] and l["details"].get("stage") == "status"]
    assert statuses == ["downloaded", "extracted", "classified", "awaiting_review"]
    q = next(iter(st.questions.values()))
    assert q["classification_source"] == "ai" and q["chapter_id"] and q["needs_review"]


def test_ai_failures_do_not_lose_questions(tmp_path):
    def boom(statement, taxonomy):
        raise RuntimeError("rate limited")
    p, st, _ = run(tmp_path, classify=boom)
    assert p.stats["questions_extracted"] == 6 and p.stats["questions_classified"] == 0
    assert sum(1 for l in st.logs if "AI classification failed" in l["message"]) == 5        # gives up after 5 consecutive errors
    assert docs(st)["JEE_Main_2023_Session_1_Shift_2_Question_Paper.pdf"]["import_status"] in ("awaiting_review", "classified")


def test_second_run_is_idempotent(tmp_path):
    p, st, site = run(tmp_path)
    n_q, n_e = len(st.questions), len(st.entries)
    p2, _, _ = run(tmp_path, store=st)
    assert len(st.questions) == n_q and len(st.entries) == n_e and p2.stats["pdfs_new"] == 0 and p2.stats["questions_extracted"] == 0
    assert len(st.documents) == 2


# ---- failure handling ---------------------------------------------------------------------------------------------------
def test_download_blocked_marks_failed_with_reason_and_manual_hint(tmp_path):
    p, st, _ = run(tmp_path, extra={QP: (403, "text/html", "Forbidden")})
    d = docs(st)["JEE_Main_2023_Session_1_Shift_2_Question_Paper.pdf"]
    assert d["import_status"] == "failed" and "blocked" in d["status_reason"] and "Manual upload" in d["status_reason"]
    assert p.stats["documents_failed"] == 1


def test_non_pdf_response_fails(tmp_path):
    p, st, _ = run(tmp_path, extra={QP: (200, "text/html", "<html>Session expired, please log in</html>")})
    d = docs(st)["JEE_Main_2023_Session_1_Shift_2_Question_Paper.pdf"]
    assert d["import_status"] == "failed" and "not_a_pdf" in d["status_reason"]


def test_corrupt_pdf_fails_cleanly(tmp_path):
    p, st, _ = run(tmp_path, extra={QP: (200, "application/pdf", b"%PDF-1.4 this is not really a pdf")})
    d = docs(st)["JEE_Main_2023_Session_1_Shift_2_Question_Paper.pdf"]
    assert d["import_status"] == "failed" and ("extract_error" in d["status_reason"] or "unexpected error" in d["status_reason"])
    assert any(l["level"] == "error" and l["document_id"] == d["id"] for l in st.logs)
    assert any(j["status"] == "failed" and j["last_error"] for j in st.jobs.values())


def test_pdf_without_text_fails_with_ocr_hint(tmp_path):
    import pymupdf
    doc = pymupdf.open(); doc.new_page(); blank = doc.tobytes(); doc.close()
    p, st, _ = run(tmp_path, extra={QP: (200, "application/pdf", blank)})
    d = docs(st)["JEE_Main_2023_Session_1_Shift_2_Question_Paper.pdf"]
    assert d["import_status"] == "failed" and "no text" in d["status_reason"].lower()


def test_missing_year_fails_with_instruction(tmp_path):
    url = H + "/past/Question_Paper.pdf"
    pages = {H + "/archive.html": (200, "text/html", archive((url, "Question Paper"))),
             url: (200, "application/pdf", pdf_bytes(tmp_path, "noyear.pdf", [["PHYSICS", "1. A long enough question statement here", "(A) a", "(B) b", "(C) c", "(D) d", "2. Another long enough question statement", "(A) a", "(B) b", "(C) c", "(D) d", "3. Third question statement is long", "(A) a", "(B) b"] + ["filler text to pass the minimum amount of text " * 1] * 6]))}
    p, st, _ = run(tmp_path, extra={**pages, QP: (404, "", ""), KEYURL: (404, "", "")})
    d = docs(st)["Question_Paper.pdf"]
    assert d["import_status"] == "failed" and d["status_reason"].startswith("missing_year") and "Set it on the document in Admin" in d["status_reason"]
    assert not st.questions


def test_solutions_pdf_is_recorded_as_skipped_with_reason(tmp_path):
    url = H + "/past/p1_solutions_final.pdf"
    p, st, _ = run(tmp_path, extra={H + "/archive.html": (200, "text/html", archive((url, "Solutions"), (QP, "Question Paper")))})
    d = docs(st)["p1_solutions_final.pdf"]
    assert d["import_status"] == "skipped" and "solutions" in d["status_reason"] and d["storage_path"] is None
    assert p.stats["documents_skipped"] >= 1


def test_identical_file_under_two_urls_is_skipped_as_duplicate(tmp_path):
    url2 = H + "/mirror/JEE_Main_2023_Session_1_Shift_2_Question_Paper_copy.pdf"
    body = pdf_bytes(tmp_path, "qp.pdf", [PAPER_PAGE1, PAPER_PAGE2], header="NTA JEE Main", footer_numbers=True)
    p, st, _ = run(tmp_path, extra={H + "/archive.html": (200, "text/html", archive((QP, "Question Paper"), (url2, "Question Paper"))), url2: (200, "application/pdf", body), QP: (200, "application/pdf", body)})
    st_ = [d["import_status"] for d in st.documents.values() if "Question_Paper" in d["source_url"]]
    assert sorted(st_) == ["extracted", "skipped"]
    assert any("duplicate" in (d["status_reason"] or "") for d in st.documents.values())
    assert len(st.questions) == 6


def test_same_question_in_another_document_is_not_imported_twice(tmp_path):
    # a second PDF of the same paper under a different shift label: identical content -> duplicates skipped, logged
    url2 = H + "/past/JEE_Main_2023_Session_1_Shift_1_Question_Paper.pdf"
    page2 = [l.replace("Shift 2", "Shift 1") for l in PAPER_PAGE1]
    body2 = pdf_bytes(tmp_path, "qp2.pdf", [page2, PAPER_PAGE2], footer_numbers=True)
    p, st, _ = run(tmp_path, extra={H + "/archive.html": (200, "text/html", archive((QP, "Question Paper"), (url2, "Question Paper"))), url2: (200, "application/pdf", body2)})
    assert len(st.questions) == 6 and p.stats["duplicates_skipped"] == 6
    assert len(st.papers) == 2


def test_everything_blocked_is_reported_as_sources_unreachable_not_success(tmp_path):
    site = FakeSite({H + "/": (403, "text/html", "Forbidden")})
    st = MemoryStore()
    p = Pipeline(st, site, None, Config(delay=0), sleep=lambda s: None, seeds=SEEDS)
    p.run()
    assert p.outcome == "sources_unreachable"
    run_row = next(iter(st.runs.values()))
    assert run_row["stats"]["outcome"] == "sources_unreachable" and "Manual upload" in run_row["stats"]["explanation"]
    assert any("blocked" in l["message"] for l in st.logs)


def test_pause_switch_stops_everything(tmp_path):
    st = MemoryStore({"import_paused": True})
    p, _, site = build(tmp_path, store=st)
    p.run()
    assert not st.runs and site.requested == []


def test_only_if_queued_exits_quietly(tmp_path):
    p, st, site = build(tmp_path, cfg=Config(delay=0, only_if_queued=True))
    p.run()
    assert not st.runs and site.requested == []


def test_manual_upload_is_processed(tmp_path):
    st = MemoryStore()
    body = pdf_bytes(tmp_path, "m.pdf", [PAPER_PAGE1, PAPER_PAGE2], header="NTA JEE Main", footer_numbers=True)
    st.put_source("jee_main/manual.pdf", body)
    doc = st.insert_document({"exam_id": 3, "doc_kind": "question_paper", "origin": "manual_upload", "source_url": None, "storage_path": "jee_main/manual.pdf",
                              "import_status": "downloaded", "exam_year": 2023, "session": "1", "shift": "2", "paper_number": None, "sha256": "x"})
    st.ensure_job(doc["id"], None)
    p = Pipeline(st, FakeSite({}), None, Config(mode="process_only", delay=0), sleep=lambda s: None)
    p.run()
    assert p.stats["questions_extracted"] == 6 and st.documents[doc["id"]]["import_status"] == "extracted"


def test_retry_after_fixing_metadata_succeeds(tmp_path):
    st = MemoryStore()
    body = pdf_bytes(tmp_path, "m.pdf", [["PHYSICS"] + PAPER_PAGE1[7:], PAPER_PAGE2 ])
    st.put_source("p.pdf", body)
    doc = st.insert_document({"exam_id": 3, "doc_kind": "question_paper", "origin": "manual_upload", "source_url": None, "storage_path": "p.pdf", "import_status": "downloaded", "exam_year": None, "sha256": "y"})
    st.ensure_job(doc["id"], None)
    Pipeline(st, FakeSite({}), None, Config(mode="process_only", delay=0), sleep=lambda s: None).run()
    assert st.documents[doc["id"]]["import_status"] == "failed" and not st.questions
    st.update_document(doc["id"], {"exam_year": 2023, "import_status": "downloaded"})        # what the Admin retry button does
    for j in st.jobs.values():
        j["status"] = "pending"
    Pipeline(st, FakeSite({}), None, Config(mode="process_only", delay=0), sleep=lambda s: None).run()
    assert st.documents[doc["id"]]["import_status"] == "extracted" and len(st.questions) == 6


def test_outcome_function():
    s = Stats()
    assert outcome(s, "full", 3, 0)[0] == "sources_unreachable"
    assert outcome(s, "full", 3, 2)[0] == "nothing_discovered"
    s["documents_failed"] = 1
    assert outcome(s, "full", 3, 2)[0] == "partial_failures"
