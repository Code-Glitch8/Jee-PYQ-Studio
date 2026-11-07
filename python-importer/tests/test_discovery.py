from sources.crawler import Seed, crawl, extract_links, follow_decision, Fetcher, looks_like_challenge, looks_like_login_wall
from sources.metadata import classify_document, classify_pdf, shift_label, parse_date
from tests.conftest import FakeSite

HOME = '<html><title>JEE Advanced</title><body><a href="/archive.html">Archive</a><a href="/login.html">Candidate login</a><a href="https://example.org/x.pdf">Elsewhere</a><a href="/documents/Information_Bulletin_2024.pdf">Bulletin</a></body></html>'
ARCHIVE = '<html><title>Previous Year Question Papers</title><body><h3>2023</h3><table><tr><td>Paper 1</td><td><a href="/past/p1_2023.pdf">Download</a></td><td><a href="/past/p1_2023_key.pdf">Answer Key</a></td></tr></table><a href="/archive_2022.html">2022 papers</a></body></html>'
ARCHIVE_2022 = '<html><body><h3>2022</h3><ul><li>Paper 2 <a href="/past/p2_2022.pdf">Question Paper</a></li></ul><a href="/past/solutions_2022.pdf">Solutions</a></body></html>'
SEED = Seed("jee_advanced", "https://jeeadv.ac.in/", "jeeadv.ac.in")


def site():
    h = "https://jeeadv.ac.in"
    return FakeSite({h + "/": (200, "text/html", HOME), h + "/archive.html": (200, "text/html", ARCHIVE), h + "/archive_2022.html": (200, "text/html", ARCHIVE_2022),
                     h + "/login.html": (200, "text/html", "<html></html>")})


def run(site_, **kw):
    logs = []
    res = crawl(site_, lambda lvl, msg, d=None: logs.append((lvl, msg, d or {})), seeds=[SEED], **kw)
    return res, logs


def test_follows_archive_pages_and_finds_pdfs_on_them():
    res, _ = run(site())
    urls = {d.url.rsplit("/", 1)[-1]: d for d in res.documents}
    assert {"p1_2023.pdf", "p1_2023_key.pdf", "p2_2022.pdf"} <= set(urls)
    assert res.pages_visited == 3                      # home, archive, archive_2022


def test_year_paper_and_kind_come_from_table_context():
    res, _ = run(site())
    d = {x.url.rsplit("/", 1)[-1]: x for x in res.documents}
    assert d["p1_2023.pdf"].meta["exam_year"] == 2023 and d["p1_2023.pdf"].meta["doc_kind"] == "question_paper" and d["p1_2023.pdf"].meta["paper_number"] == 1
    assert d["p1_2023_key.pdf"].meta["doc_kind"] == "answer_key"
    assert d["p2_2022.pdf"].meta["exam_year"] == 2022 and d["p2_2022.pdf"].meta["paper_number"] == 2


def test_question_papers_are_kept_apart_from_keys_solutions_and_bulletins():
    res, _ = run(site())
    d = {x.url.rsplit("/", 1)[-1]: x for x in res.documents}
    assert d["solutions_2022.pdf"].skip_reason and "solutions" in d["solutions_2022.pdf"].skip_reason
    assert d["Information_Bulletin_2024.pdf"].skip_reason == "information bulletin"
    assert d["p1_2023.pdf"].skip_reason is None


def test_source_page_and_pdf_url_are_preserved():
    res, _ = run(site())
    d = next(x for x in res.documents if x.url.endswith("p1_2023.pdf"))
    assert d.page_url == "https://jeeadv.ac.in/archive.html" and d.url == "https://jeeadv.ac.in/past/p1_2023.pdf"


def test_depth_limit_is_respected_and_logged():
    res, logs = run(site(), max_depth=1)
    assert not any(d.url.endswith("p2_2022.pdf") for d in res.documents)
    assert any("depth limit" in m for _, m, _ in logs)


def test_login_and_offsite_links_are_not_followed():
    s = site()
    run(s)
    assert "https://jeeadv.ac.in/login.html" not in s.requested and not any("example.org" in u for u in s.requested)


def test_robots_disallowed_pages_are_not_fetched_and_are_logged():
    s = site()
    s.disallow = {"https://jeeadv.ac.in/archive"}
    res, logs = run(s)
    assert not any(d.url.endswith("p1_2023.pdf") for d in res.documents)
    assert any(f["reason"] == "robots_disallowed" for f in res.failures)
    assert any("robots_disallowed" in m for _, m, _ in logs)


def test_blocked_site_is_reported_not_bypassed():
    s = FakeSite({"https://jeeadv.ac.in/": (403, "text/html", "Forbidden")})
    res, logs = run(s)
    assert res.seeds_reached == 0 and res.failures[0]["reason"] == "blocked"
    assert s.requested == ["https://jeeadv.ac.in/"]            # one attempt, no retry with other headers
    assert any(lvl == "warn" and "blocked" in m for lvl, m, _ in logs)


def test_captcha_page_is_detected_and_skipped():
    s = FakeSite({"https://jeeadv.ac.in/": (200, "text/html", "<html>Please solve the CAPTCHA</html>")})
    res, _ = run(s)
    assert res.failures[0]["reason"] == "challenge_page" and res.documents == []
    assert looks_like_challenge("<title>Just a moment...</title>")


def test_login_wall_detected():
    assert looks_like_login_wall('<html><form>Sign in <input type="password"></form></html>')
    assert not looks_like_login_wall("<html>" + "text " * 2000 + '<input type="password"></html>')


def test_pdf_detection_variants():
    html = ('<a href="a.pdf">A</a><a href="B.PDF?x=1">B</a><a href="/download?file=7">C</a>'
            '<a href="javascript:void(0)" onclick="window.open(\'files/d.pdf\')">D</a><iframe src="e.pdf"></iframe><a href="page.html">P</a><a href="mailto:x@y.z">M</a>')
    pdfs, pages, _ = extract_links(html, "https://site.org/papers/")
    got = {p["url"] for p in pdfs}
    assert {"https://site.org/papers/a.pdf", "https://site.org/papers/B.PDF?x=1", "https://site.org/download?file=7", "https://site.org/papers/files/d.pdf", "https://site.org/papers/e.pdf"} <= got
    assert [p["url"] for p in pages] == ["https://site.org/papers/page.html"]


def test_download_style_link_must_really_be_a_pdf():
    h = "https://jeeadv.ac.in"
    s = FakeSite({h + "/": (200, "text/html", '<a href="/download?file=1">Question Paper 2021</a><a href="/download?file=2">Question Paper 2020</a>'),
                  h + "/download?file=1": (200, "application/pdf", b"%PDF-1.4"), h + "/download?file=2": (200, "text/html", "<html/>")})
    res, _ = run(s)
    assert [d.url for d in res.documents] == [h + "/download?file=1"]


def test_shared_nta_site_only_yields_jee_documents():
    seed = Seed("jee_main", "https://www.nta.ac.in/", "nta.ac.in", require_jee=True)
    s = FakeSite({"https://www.nta.ac.in/": (200, "text/html", '<a href="/neet_2023_question_paper.pdf">NEET 2023 Question Paper</a><a href="/jee_main_2023_question_paper.pdf">JEE Main 2023 Question Paper</a>')})
    res = crawl(s, lambda *a, **k: None, seeds=[seed])
    kept = [d for d in res.documents if not d.skip_reason]
    assert [d.url.rsplit("/", 1)[-1] for d in kept] == ["jee_main_2023_question_paper.pdf"]
    assert any(d.skip_reason and "not a JEE" in d.skip_reason for d in res.documents)


def test_follow_decision_reasons():
    assert follow_decision("https://other.com/a", "x", SEED) == (False, "off_site")
    assert follow_decision("https://jeeadv.ac.in/login", "x", SEED)[1] == "login_or_media_link"
    assert follow_decision("https://jeeadv.ac.in/contact.html", "Contact us", SEED)[1] == "no_archive_keyword"
    assert follow_decision("https://jeeadv.ac.in/archive.html", "Archive", SEED)[0]


# ---- multi-shift / multi-session identification ------------------------------------------------------------------
def test_multi_shift_papers_are_distinguished():
    a = classify_document("https://x/JEE_Main_2023_Session_1_Shift_1_Question_Paper.pdf")
    b = classify_document("https://x/JEE_Main_2023_Session_1_Shift_2_Question_Paper.pdf")
    c = classify_document("https://x/JEE_Main_2023_Session_2_Shift_2_Question_Paper.pdf")
    key = lambda m: (m["exam_year"], m["session"], m["shift"], m["paper_number"])
    assert len({key(a), key(b), key(c)}) == 3 and key(a) == (2023, "1", "1", None)


def test_dated_multi_day_papers_get_unique_shift_labels():
    a = classify_document("https://x/24.02.2021_Shift_1_Question_Paper.pdf", "", "JEE Main 2021 Session 1")
    b = classify_document("https://x/25.02.2021_Shift_1_Question_Paper.pdf", "", "JEE Main 2021 Session 1")
    assert shift_label(a["shift"], a["exam_date"]) == "2021-02-24 S1" != shift_label(b["shift"], b["exam_date"])
    assert str(parse_date("26th February, 2021")) == "2021-02-26"


def test_morning_evening_and_roman_numerals():
    assert classify_document("https://x/JEE_Main_2022_Session_II_Evening_Question_Paper.pdf")["shift"] == "2"
    assert classify_document("https://x/JEE_Main_2022_Session_II_Evening_Question_Paper.pdf")["session"] == "2"
    assert classify_document("https://x/2020_Shift-I_paper.pdf")["shift"] == "1"


def test_ambiguous_year_is_reported_not_guessed():
    m = classify_document("https://x/JEE_2021_2022_Question_Paper.pdf")
    assert m["exam_year"] is None and "several years" in m["year_problem"]


def test_unknown_documents_are_skipped_with_reason():
    assert classify_document("https://x/random_file.pdf")["skip_reason"]
    assert classify_document("https://x/JEE_Main_2024_Paper_2A_BArch_Question_Paper.pdf")["skip_reason"]


def test_provisional_vs_final_key():
    assert classify_document("https://x/p1_provisional_keys.pdf")["key_version"] == "provisional"
    assert classify_document("https://x/Final_Answer_Key_2022.pdf")["key_version"] == "final"


def test_legacy_classify_pdf_still_works():
    m = classify_pdf("https://x/JEE_Main_2023_Session_1_Shift_2_Question_Paper.pdf", "")
    assert m["exam_year"] == 2023 and m["session"] == "1" and m["shift"] == "2" and m["doc_kind"] == "question_paper"


# ---- rate limiting -------------------------------------------------------------------------------------------------
def test_fetcher_waits_between_requests_to_one_host():
    class R:
        status_code = 200; headers = {"Content-Type": "text/html"}; text = "<html>ok</html>"
        def iter_content(self, n): yield b"<html>ok</html>"
        def close(self): pass
    class Sess:
        headers = {}
        def get(self, url, **kw):
            r = R()
            if url.endswith("robots.txt"):
                r.status_code, r.text = 404, ""
            return r
    sleeps, t = [], [100.0]
    f = Fetcher(delay=3.0, session=Sess(), sleep=lambda s: (sleeps.append(s), t.__setitem__(0, t[0] + s)), clock=lambda: t[0])
    f.get("https://a.org/1"); f.get("https://a.org/2")
    assert sleeps and all(abs(s - 3.0) < 0.01 or s <= 3.0 for s in sleeps) and sum(sleeps) >= 3.0


def test_host_dropped_after_repeated_blocks():
    class R:
        status_code = 403; headers = {}; text = "no"
        def iter_content(self, n): yield b"no"
        def close(self): pass
    class Sess:
        headers = {}
        def get(self, url, **kw):
            r = R()
            if url.endswith("robots.txt"):
                r.status_code, r.text = 404, ""
            return r
    f = Fetcher(delay=0, session=Sess(), sleep=lambda s: None, block_limit=2)
    reasons = [f.get(f"https://a.org/{i}").reason for i in range(4)]
    assert reasons[:2] == ["blocked", "blocked"] and reasons[2:] == ["host_dropped", "host_dropped"]
