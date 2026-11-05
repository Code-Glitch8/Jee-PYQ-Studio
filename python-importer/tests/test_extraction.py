import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from extraction.pdf_text import split_questions, parse_answer_key
from classification.classifier import parse_reply
from sources.official import looks_like_challenge, classify_pdf

SAMPLE = """1. A body of mass 2 kg moves at 3 m/s. Its kinetic energy is
(A) 3 J
(B) 9 J
(C) 6 J
(D) 12 J
2. The value of 2. 5 plus 1 is
(A) 3.5
(B) 4
3. Find the integer n such that n squared is 49."""

def test_splits_in_sequence_and_ignores_stray_numbers():
    qs = split_questions(SAMPLE)
    assert [q["number"] for q in qs] == [1, 2, 3]
    assert len(qs[0]["options"]) == 4 and qs[0]["options"][1]["label"] == "B"

def test_answer_key():
    assert parse_answer_key("1 B\n2 A,C\n3 49")[2] == "A,C"

def test_classifier_reply_is_validated():
    d = parse_reply('```json\n{"subject":"physics","chapter":"Kinematics","difficulty":"extreme","confidence":1.7}\n```')
    assert d["difficulty"] is None and d["confidence"] == 1.0

def test_challenge_pages_detected_not_bypassed():
    assert looks_like_challenge("<html>Please solve the CAPTCHA</html>")

def test_pdf_metadata_guess():
    m = classify_pdf("https://x/JEE_Main_2023_Session_1_Shift_2_Question_Paper.pdf", "")
    assert m["exam_year"] == 2023 and m["session"] == "1" and m["shift"] == "2" and m["doc_kind"] == "question_paper"
