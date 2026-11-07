"""Compatibility facade. The implementation now lives in sources.crawler (discovery) and sources.metadata (naming)."""
from sources.crawler import SEEDS, UA, Fetcher, crawl, looks_like_challenge   # noqa: F401
from sources.metadata import classify_pdf                                     # noqa: F401

SOURCES = [{"exam": s.exam, "start": s.start} for s in SEEDS]
DELAY_SECONDS = 3.0
_default = Fetcher()

def allowed(url: str) -> bool:
    return _default.allowed(url)

def polite_get(url: str, **kw):
    r = _default.get(url, "pdf" if url.lower().endswith(".pdf") else "html")
    return r
