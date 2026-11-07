"""Compatibility layer for the original API. New code should use extraction.layout / questions / answer_key."""
from extraction.layout import read_pdf
from extraction.questions import split_questions            # noqa: F401
from extraction.answer_key import parse_answer_key           # noqa: F401


def extract_text(path: str, min_chars_per_page: int = 80) -> tuple[str, bool]:
    c = read_pdf(path)
    return c.text, bool(c.ocr_pages)
