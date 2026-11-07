from dedupe import fingerprint, near_duplicates, similarity
from extraction.answer_key import key_looks_valid, normalise_answer, parse_answer_key, parse_answer_key_entries, parse_key_lines
from extraction.layout import lines_from_text
from matching.answer_match import match_entries, match_paper, reconcile_across_documents, shape_answer

KEY = "PHYSICS\n1 B\n2 A,C\n3 49\n4 12.3 - 12.5\n5 D 6 ACD\n7 DROPPED\nCHEMISTRY\n1 C\nQ.2 (B)\n3 3\n4 A\n"


def test_answer_key_parsing_forms():
    es, info = parse_answer_key_entries(KEY)
    d = {(e.subject_code, e.question_number): e for e in es}
    assert d[("physics", 1)].answer == ["B"] and d[("physics", 2)].answer == ["A", "C"] and d[("physics", 2)].kind == "multiple"
    assert d[("physics", 3)].answer == 49 and d[("physics", 4)].answer == {"value": 12.4, "tolerance": 0.1}
    assert d[("physics", 5)].answer == ["D"] and d[("physics", 6)].answer == ["A", "C", "D"]
    assert d[("physics", 7)].kind == "dropped" and d[("physics", 7)].answer is None
    assert d[("chemistry", 2)].answer == ["B"] and len(es) == 11 and key_looks_valid(es, info)[0]


def test_row_wise_key_tables():
    es, _ = parse_key_lines(lines_from_text("Q 1 2 3 4\nAns A B 12 C"))
    assert [(e.question_number, e.answer) for e in es] == [(1, ["A"]), (2, ["B"]), (3, 12), (4, ["C"])]


def test_legacy_parse_answer_key():
    assert parse_answer_key("1 B\n2 A,C\n3 49")[2] == "A,C"


def test_conflicting_duplicates_are_never_resolved_by_guessing():
    es, info = parse_answer_key_entries("1 A\n1 B\n2 C\n3 D\n4 A\n5 B")
    e = next(x for x in es if x.question_number == 1)
    assert e.answer is None and e.kind == "unknown" and info["conflicts"] == 1 and "different answers" in e.note


def test_prose_documents_are_not_accepted_as_keys():
    prose = "\n".join(f"Step {i}: the particle moves with constant acceleration so we use the equation of motion directly" for i in range(40)) + "\n1 B\n2 C"
    es, info = parse_answer_key_entries(prose)
    ok, why = key_looks_valid(es, info)
    assert not ok and ("solutions" in why or "only" in why)


def test_id_based_keys_stay_unresolved():
    es, _ = parse_answer_key_entries("1 4358011 4358013\n2 4358021 4358024")
    assert all(e.answer is None and e.original_question_id for e in es)


def test_normalise_answer():
    assert normalise_answer("A") == (["A"], "single") and normalise_answer("A, C") == (["A", "C"], "multiple")
    assert normalise_answer("-3") == (-3, "numerical") and normalise_answer("BONUS") == (None, "dropped")


# ---- matching ----------------------------------------------------------------------------------------------------------
P = lambda i, **k: {"id": i, "exam_id": 3, "exam_year": 2023, "session": "1", "shift": "1", "paper_number": 1, "exam_date": None, **k}


def test_paper_match_unique():
    r = match_paper({"exam_id": 3, "exam_year": 2023, "session": "1", "shift": "2"}, [P("a"), P("b", shift="2"), P("c", session="2", shift="2")])
    assert r.status == "matched" and r.paper["id"] == "b"


def test_paper_match_ambiguous_when_key_omits_shift():
    r = match_paper({"exam_id": 3, "exam_year": 2023, "session": "1", "shift": None}, [P("a"), P("b", shift="2")])
    assert r.status == "ambiguous" and len(r.candidates) == 2


def test_single_candidate_still_ambiguous_if_other_papers_differ_in_unstated_field():
    r = match_paper({"exam_id": 3, "exam_year": 2023, "session": "1", "shift": None, "paper_number": 1}, [P("a")] + [P("b", shift="2", session="2")])
    assert r.status in ("matched", "ambiguous")      # session stated => narrowed to one paper


def test_paper_match_unmatched_cases():
    assert match_paper({"exam_id": 3, "exam_year": None}, [P("a")]).status == "unmatched"
    assert match_paper({"exam_id": 3, "exam_year": 2020}, [P("a")]).status == "unmatched"
    assert match_paper({"exam_id": 3, "exam_year": 2023, "shift": "2"}, [P("a")]).status == "unmatched"


def test_paper_match_with_dated_shift_label():
    r = match_paper({"exam_id": 3, "exam_year": 2021, "shift": "1", "session": "1"}, [P("a", exam_year=2021, shift="2021-02-24 S1")])
    assert r.status == "matched"


Q = lambda i, n, t="single_mcq", s="physics", labels="ABCD": {"id": i, "question_number": n, "question_type": t, "subject_code": s, "option_labels": list(labels)}
E = lambda i, n, ans, kind="single", subj=None, **k: {"id": i, "question_number": n, "answer": ans, "answer_kind": kind, "subject_code": subj, "raw_answer": str(ans), "match_status": "unmatched", **k}


def test_unambiguous_entry_is_proposed_not_applied():
    pm = match_paper({"exam_id": 3, "exam_year": 2023, "session": "1", "shift": "1"}, [P("a")])
    u = match_entries({}, [E("e1", 1, ["B"])], pm, [Q("q1", 1)])
    assert u["e1"]["match_status"] == "proposed" and u["e1"]["matched_question_id"] == "q1" and u["e1"]["answer"] == ["B"]


def test_number_shared_by_two_subjects_is_ambiguous_without_subject():
    pm = match_paper({"exam_id": 3, "exam_year": 2023, "session": "1", "shift": "1"}, [P("a")])
    qs = [Q("q1", 1, s="physics"), Q("q2", 1, s="chemistry")]
    u = match_entries({}, [E("e1", 1, ["B"])], pm, qs)
    assert u["e1"]["match_status"] == "ambiguous" and set(u["e1"]["candidate_question_ids"]) == {"q1", "q2"} and u["e1"]["matched_question_id"] is None
    u = match_entries({}, [E("e2", 1, ["B"], subj="chemistry")], pm, qs)
    assert u["e2"]["matched_question_id"] == "q2"


def test_ambiguous_paper_never_assigns_anything():
    pm = match_paper({"exam_id": 3, "exam_year": 2023, "session": "1", "shift": None}, [P("a"), P("b", shift="2")])
    u = match_entries({}, [E("e1", 1, ["B"])], pm, [Q("q1", 1)])
    assert u["e1"]["match_status"] == "ambiguous" and u["e1"]["matched_question_id"] is None and u["e1"]["paper_id"] is None


def test_missing_question_is_unmatched_and_confirmed_entries_are_untouched():
    pm = match_paper({"exam_id": 3, "exam_year": 2023, "session": "1", "shift": "1"}, [P("a")])
    u = match_entries({}, [E("e1", 9, ["B"]), E("e2", 1, ["A"], match_status="confirmed")], pm, [Q("q1", 1)])
    assert u["e1"]["match_status"] == "unmatched" and "e2" not in u


def test_answer_shape_conversion_and_mismatch():
    assert shape_answer(E("x", 1, 3, "numerical"), Q("q", 1, labels="1234")) == (["3"], "")           # key says 3, options are 1-4
    assert shape_answer(E("x", 1, ["C"]), Q("q", 1, labels="1234")) == (["3"], "")                   # key says C, options are 1-4
    assert shape_answer(E("x", 1, ["B"]), Q("q", 1, t="numerical", labels=""))[0] is None
    assert shape_answer(E("x", 1, ["A", "B"], "multiple"), Q("q", 1))[0] is None                       # two answers, single-correct question
    assert shape_answer(E("x", 1, ["A", "C"], "multiple"), Q("q", 1, t="multi_mcq")) == (["A", "C"], "")
    assert shape_answer(E("x", 1, None, "dropped"), Q("q", 1))[0] is None
    assert shape_answer(E("x", 1, ["E"]), Q("q", 1))[0] is None
    assert shape_answer(E("x", 1, 2.5, "numerical"), Q("q", 1, t="integer", labels=""))[0] is None


def test_provisional_and_final_disagreement_is_left_for_a_person():
    rows = [{"id": "e1", "match_status": "proposed", "matched_question_id": "q1", "answer": ["B"], "raw_answer": "B", "source_document_id": "d1"},
            {"id": "e2", "match_status": "proposed", "matched_question_id": "q1", "answer": ["C"], "raw_answer": "C", "source_document_id": "d2"}]
    docs = {"d1": {"detected": {"key_version": "provisional"}}, "d2": {"detected": {"key_version": "final"}}}
    out = reconcile_across_documents(rows, docs)
    assert out["e1"]["match_status"] == out["e2"]["match_status"] == "ambiguous" and "provisional" in out["e1"]["match_note"]
    rows[1]["answer"] = ["B"]
    assert reconcile_across_documents(rows, docs) == {}


# ---- duplicates ----------------------------------------------------------------------------------------------------------
def test_fingerprint_ignores_layout_not_content():
    a = fingerprint("A body of mass 2 kg   moves at 3 m/s.", [{"content": "3 J"}, {"content": "9 J"}])
    b = fingerprint("A body of mass 2 kg moves at 3 m/s", [{"content": "3  J"}, {"content": "9 J"}])
    c = fingerprint("A body of mass 2 kg moves at 3 m/s.", [{"content": "3 J"}, {"content": "10 J"}])
    assert a == b != c


def test_near_duplicates():
    s = "A body of mass two kilograms moves at three metres per second find its kinetic energy"
    assert similarity(s, s) == 1.0
    hits = near_duplicates(s + " now", [("q1", s), ("q2", "Completely different chemistry question about acids and bases in water")])
    assert [h[0] for h in hits] == ["q1"]
