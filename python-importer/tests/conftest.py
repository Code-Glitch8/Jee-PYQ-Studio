import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

from sources.crawler import FetchResult


def make_pdf(path, pages: list[list[str]], header: str | None = None, footer_numbers: bool = False) -> str:
    """Build a text PDF. Each page is a list of lines. Optional running header and page-number footer."""
    doc = fitz.open()
    for n, lines in enumerate(pages, 1):
        page = doc.new_page(width=595, height=842)
        if header:
            page.insert_text((60, 30), header, fontsize=9)
        y = 80
        for line in lines:
            page.insert_text((60, y), line, fontsize=11)
            y += 16
        if footer_numbers:
            page.insert_text((290, 820), f"Page {n}", fontsize=9)
    doc.save(path)
    doc.close()
    return str(path)


def make_scanned_pdf(path, lines: list[str]) -> str:
    """A PDF whose only content is a picture of text (no text layer)."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    y = 120
    for l in lines:
        d.text((100, y), l, fill="black", font=font)
        y += 60
    buf = io.BytesIO()
    img.save(buf, "PNG")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(path)
    doc.close()
    return str(path)


PAPER_PAGE1 = [
    "JEE Main 2023 Session 1 Shift 2", "Question Paper", "READ THE INSTRUCTIONS CAREFULLY",
    "1. Each question has four options.", "2. Do not use a calculator.", "3. Rough work in the space provided.",
    "PHYSICS", "SECTION A", "Only one of these four options is correct.",
    "1. A body of mass 2 kg moves at 3 m/s. Its kinetic energy is", "(A) 3 J", "(B) 9 J", "(C) 6 J", "(D) 12 J",
    "2. Solve x + y = 5 and",
    "2) x - y = 1. Then x equals",
    "(A) 1", "(B) 2", "(C) 3", "(D) 4",
]
PAPER_PAGE2 = [
    "3. The speed is 3. 5 m/s and the mass is", "4 kg. Find the momentum in SI units.", "(A) 14", "(B) 12", "(C) 10", "(D) 9",
    "SECTION B", "The answer to each question is a non-negative integer.",
    "4. The number of solutions of x squared equal to 49 is",
    "5. If the sum of two numbers is 12 and their difference is 4, the larger number is",
    "CHEMISTRY", "SECTION A", "Only one of these four options is correct.",
    "6. Which gas is produced when zinc reacts with dilute acid?", "(A) Oxygen", "(B) Hydrogen", "(C) Nitrogen", "(D) Chlorine",
]
KEY_PAGE = ["JEE Main 2023 Session 1 Shift 2 Final Answer Key", "PHYSICS", "1 C", "2 B", "3 A", "4 2", "5 8", "CHEMISTRY", "6 B", "7 A", "8 C"]


@pytest.fixture
def paper_pdf(tmp_path):
    return make_pdf(tmp_path / "paper.pdf", [PAPER_PAGE1, PAPER_PAGE2], header="NTA JEE Main", footer_numbers=True)


class FakeSite:
    """Stand-in for Fetcher: url -> (status, content_type, body). Records every request."""
    def __init__(self, pages: dict, robots_disallow: set | None = None):
        self.pages, self.requested = pages, []
        self.disallow = robots_disallow or set()
        self._blocks = {}
        self.block_limit = 3

    def allowed(self, url):
        return not any(url.startswith(p) for p in self.disallow)

    def host_dropped(self, host):
        return False

    def head_is_pdf(self, url):
        r = self.pages.get(url)
        return bool(r and r[1] == "application/pdf")

    def get(self, url, expect="html", max_bytes=None):
        self.requested.append(url)
        if not self.allowed(url):
            return FetchResult(False, url, None, "robots_disallowed", "robots.txt disallows this URL")
        status, ctype, body = self.pages.get(url, (404, "text/html", b"not found"))
        body = body.encode() if isinstance(body, str) else body
        if status in (403, 429):
            return FetchResult(False, url, status, "blocked" if status == 403 else "rate_limited", f"HTTP {status}")
        if status >= 400:
            return FetchResult(False, url, status, "http_error", f"HTTP {status}")
        if expect == "html" and b"captcha" in body.lower():
            return FetchResult(False, url, status, "challenge_page", "page looks like a CAPTCHA")
        return FetchResult(True, url, status, "ok", "", body, ctype)
