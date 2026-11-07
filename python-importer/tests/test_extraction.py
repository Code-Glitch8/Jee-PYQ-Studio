import shutil

import pytest

from classification.classifier import parse_reply
from extraction.layout import lines_from_text, read_pdf
from extraction.pdf_text import extract_text
from extraction.questions import parse_questions, split_questions
from sources.crawler import looks_like_challenge
from sources.metadata import classify_pdf
from tests.conftest import make_pdf, make_scanned_pdf

SAMPLE = """1. A body of mass 2 kg moves at 3 m/s. Its kinetic energy is
(A) 3 J
(B) 9 J
(C) 6 J
(D) 12 J
2. The value of 2. 5 plus 1 is
(A) 3.5
(B) 4
3. Find the integer n such that n squared is 49."""


def test_splits_in_sequence():
    qs = split_questions(SAMPLE)
    assert [q["number"] for q in qs] == [1, 2, 3]
    assert len(qs[0]["options"]) == 4 and qs[0]["options"][1]["label"] == "B"


def test_number_inside_a_wrapped_equation_does_not_start_a_question():
    text = ("1. Solve the system of equations\n2) x + y = 5 and\n3. 5 m/s speed gives\n(A) 1\n(B) 2\n(C) 3\n(D) 4\n"
            "2. The next question begins here properly\n(A) a\n(B) b\n(C) c\n(D) d\n3. Third question text goes here\n(A) a\n(B) b\n(C) c\n(D) d")
    qs = split_questions(text)
    assert [q["number"] for q in qs] == [1, 2, 3]
    assert "2) x + y = 5" in qs[0]["statement"] and "3. 5 m/s" in qs[0]["statement"]


def test_decimal_and_numeric_lines_are_not_markers():
    text = "1. A rod of length\n2.5 m is pulled with force\n4.2 N and the work is\n(A) 1\n(B) 2\n(C) 3\n(D) 4\n2. Next question text here\n(A) a\n(B) b"
    qs = split_questions(text)
    assert [q["number"] for q in qs] == [1, 2] and "2.5 m" in qs[0]["statement"]


def test_instruction_list_before_first_subject_is_not_a_question_chain():
    text = "1. Each question has four options.\n2. Do not use a calculator.\nPHYSICS\n1. First real question here is long enough\n(A) a\n(B) b\n(C) c\n(D) d\n2. Second real question here is long\n(A) a\n(B) b\n(C) c\n(D) d"
    qs = split_questions(text)
    assert [q["number"] for q in qs] == [1, 2] and qs[0]["statement"].startswith("First real")


def test_numbering_may_restart_per_subject_and_subject_is_recorded():
    block = "{n}. A sufficiently long question statement number {n}\n(A) a\n(B) b\n(C) c\n(D) d\n"
    text = "PHYSICS\n" + block.format(n=1) + block.format(n=2) + "CHEMISTRY\n" + block.format(n=1) + block.format(n=2)
    qs = split_questions(text)
    assert [(q["subject_hint"], q["number"]) for q in qs] == [("physics", 1), ("physics", 2), ("chemistry", 1), ("chemistry", 2)]


def test_numbering_may_continue_across_subjects():
    block = "{n}. A sufficiently long question statement number {n}\n(A) a\n(B) b\n(C) c\n(D) d\n"
    text = "PHYSICS\n" + block.format(n=1) + block.format(n=2) + "CHEMISTRY\n" + block.format(n=3) + block.format(n=4)
    assert [q["number"] for q in split_questions(text)] == [1, 2, 3, 4]


def test_missing_number_is_reported_not_invented():
    block = "{n}. A sufficiently long question statement number {n}\n(A) a\n(B) b\n(C) c\n(D) d\n"
    _, info = parse_questions(lines_from_text(block.format(n=1) + block.format(n=2) + block.format(n=4) + block.format(n=5)))
    assert info["missing_numbers"] == [3]


def test_question_types_from_section_instructions():
    text = ("PHYSICS\nSECTION 1\nONLY ONE of these four options is correct.\n1. A single correct question that is long enough\n(A) a\n(B) b\n(C) c\n(D) d\n"
            "SECTION 2\nONE OR MORE THAN ONE of these four option(s) is(are) correct answer(s).\n2. A multiple correct question that is long enough\n(A) a\n(B) b\n(C) c\n(D) d\n"
            "SECTION 3\nThe answer to each question is a NON-NEGATIVE INTEGER.\n3. An integer question that is long enough to read\n"
            "SECTION 4\nThe answer is a numerical value correct up to the 2nd decimal place.\n4. A decimal answer question that is long enough")
    assert [q["question_type"] for q in split_questions(text)] == ["single_mcq", "multi_mcq", "integer", "numerical"]


def test_inline_options_are_split():
    qs = split_questions("1. Which one of the following is the largest value here?\n(A) 7 (B) 8 (C) 9 (D) 10\n2. Another long enough question statement\n(A) a\n(B) b")
    assert [o["content"] for o in qs[0]["options"]] == ["7", "8", "9", "10"]


def test_list_inside_stem_is_not_mistaken_for_options():
    text = "1. Match the items below\n(A) alpha (B) beta\nThen choose the right order from the choices\n(1) A-B\n(2) B-A\n(3) A only\n(4) B only\n2. Next question statement is here\n(1) a\n(2) b"
    q = split_questions(text)[0]
    assert [o["label"] for o in q["options"]] == ["1", "2", "3", "4"]


def test_paragraph_is_attached_to_its_questions():
    text = ("PHYSICS\n1. Opening question that is long enough here\n(A) a\n(B) b\n(C) c\n(D) d\n"
            "Paragraph for Questions 2 and 3: A ball is thrown upward.\n2. What is its maximum height reached?\n(A) a\n(B) b\n(C) c\n(D) d\n3. How long does it stay up?\n(A) a\n(B) b\n(C) c\n(D) d")
    qs = split_questions(text)
    assert "A ball is thrown upward" in qs[1]["statement"] and "A ball is thrown upward" in qs[2]["statement"] and "A ball" not in qs[0]["statement"]


def test_matrix_match_is_detected():
    q = split_questions("1. Match List-I with List-II and select the answer\nList-I (P) a (Q) b\nList-II (1) x (2) y\n(A) P-1\n(B) P-2\n(C) Q-1\n(D) Q-2\n2. Following question that is long\n(A) a\n(B) b")[0]
    assert q["question_type"] == "matrix_match"


def test_math_flag_and_figure_flag():
    q = split_questions("1. Evaluate $x^{2}$ where θ = π/3 and √2 appears, see the figure shown below\n(A) a\n(B) b\n(C) c\n(D) d\n2. Plain question here with words\n(A) a\n(B) b")[0]
    assert q["flags"]["math_heavy"] and q["flags"]["mentions_figure"]


# ---- real PDFs --------------------------------------------------------------------------------------------------------
def test_multi_page_question_is_kept_whole_and_margins_removed(paper_pdf):
    c = read_pdf(paper_pdf)
    assert c.dropped_header_footer_lines >= 3                      # "NTA JEE Main" x2 + page numbers
    qs, info = parse_questions(c.lines)
    by = {q.number: q for q in qs}
    assert sorted(by) == [1, 2, 3, 4, 5, 6] and not info["missing_numbers"]
    assert "NTA JEE Main" not in " ".join(q.statement for q in qs)
    assert by[2].statement.endswith("Then x equals") and "x - y = 1" in by[2].statement
    assert by[3].statement == "The speed is 3. 5 m/s and the mass is 4 kg. Find the momentum in SI units."
    assert by[3].page_start == 2 and [o["label"] for o in by[1].options] == list("ABCD")
    assert (by[4].question_type, by[6].question_type) == ("integer", "single_mcq")
    assert by[1].subject_hint == "physics" and by[6].subject_hint == "chemistry"


def test_question_spanning_two_pages(tmp_path):
    p1 = ["PHYSICS", "1. A particle moves along a straight line and its position at time t is described by the long sentence that"]
    p2 = ["continues on the next page until it reaches the question.", "(A) 1", "(B) 2", "(C) 3", "(D) 4", "2. Another question that is long enough to parse", "(A) a", "(B) b"]
    path = make_pdf(tmp_path / "span.pdf", [p1, p2])
    qs, _ = parse_questions(read_pdf(path).lines)
    assert qs[0].page_start == 1 and qs[0].page_end == 2 and len(qs[0].pieces) == 2
    assert "continues on the next page" in qs[0].statement and len(qs[0].options) == 4


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")
def test_scanned_pdf_is_ocrd(tmp_path):
    path = make_scanned_pdf(tmp_path / "scan.pdf", ["PHYSICS", "1. A body of mass two kilograms moves quickly", "(A) three", "(B) nine", "(C) six", "(D) twelve",
                                                    "2. The second question is about energy", "(A) one", "(B) two", "(C) three", "(D) four"])
    c = read_pdf(path)
    assert c.ocr_pages == [1] and c.chars > 100
    qs, _ = parse_questions(c.lines)
    assert [q.number for q in qs] == [1, 2] and qs[0].ocr and len(qs[0].options) == 4


def test_figure_is_cropped_and_attached(tmp_path):
    import pymupdf as fitz
    from extraction import figures
    doc = fitz.open(); page = doc.new_page(width=595, height=842)
    page.insert_text((60, 80), "1. In the circuit shown below find the current", fontsize=11)
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(100, 100, 300, 220)); shape.draw_circle(fitz.Point(200, 160), 30); shape.finish(color=(0, 0, 0)); shape.commit()
    page.insert_text((60, 260), "(A) 1", fontsize=11); page.insert_text((60, 276), "(B) 2", fontsize=11)
    page.insert_text((60, 300), "2. Another question that is long enough here", fontsize=11)
    path = str(tmp_path / "fig.pdf"); doc.save(path); doc.close()
    qs, _ = parse_questions(read_pdf(path).lines)
    got = figures.collect(path, [{"number": q.number, "pieces": q.pieces, "needs_snapshot": q.flags["mentions_figure"]} for q in qs], set())
    assert 0 in got and {i["kind"] for i in got[0]} == {"figure", "snapshot"} and got[0][0]["png"][:4] == b"\x89PNG"
    assert 1 not in got


def test_text_extraction_compat(paper_pdf):
    text, used_ocr = extract_text(paper_pdf)
    assert "kinetic energy" in text and used_ocr is False


def test_classifier_reply_is_validated():
    d = parse_reply('```json\n{"subject":"physics","chapter":"Kinematics","difficulty":"extreme","confidence":1.7}\n```')
    assert d["difficulty"] is None and d["confidence"] == 1.0
    assert parse_reply("[1,2]") is None and parse_reply("nonsense") is None
    assert parse_reply('{"confidence":"high"}')["confidence"] == 0.0


def test_challenge_pages_detected_not_bypassed():
    assert looks_like_challenge("<html>Please solve the CAPTCHA</html>")


def test_pdf_metadata_guess():
    m = classify_pdf("https://x/JEE_Main_2023_Session_1_Shift_2_Question_Paper.pdf", "")
    assert m["exam_year"] == 2023 and m["session"] == "1" and m["shift"] == "2" and m["doc_kind"] == "question_paper"
