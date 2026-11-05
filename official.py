"""Discovery of publicly accessible PDFs on the official sites.

Rules: obey robots.txt, rate-limit requests, never try to get past CAPTCHAs, logins or anti-bot pages.
If a page looks like a challenge page it is skipped and reported, not worked around.
"""
import re, time, urllib.robotparser
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

UA = "JEE-PYQ-Studio-Importer/1.0 (personal study tool; respects robots.txt)"
DELAY_SECONDS = 3.0
# status for documents found on these hosts; everything else would need manual verification
SOURCES = [
    {"exam": "jee_main", "start": "https://jeemain.nta.nic.in/"},
    {"exam": "jee_main", "start": "https://www.nta.ac.in/"},
    {"exam": "jee_advanced", "start": "https://jeeadv.ac.in/"},
]
KEYWORDS = re.compile(r"(question[\s_-]*paper|paper[\s_-]*[12]|answer[\s_-]*key|final[\s_-]*key|memory[\s_-]*based|shift)", re.I)
CHALLENGE = re.compile(r"(captcha|are you a robot|access denied|attention required|verify you are human)", re.I)

_robots = {}
_last = 0.0

def allowed(url: str) -> bool:
    host = urlparse(url)
    base = f"{host.scheme}://{host.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser(base + "/robots.txt")
        try:
            rp.read()
        except Exception:
            rp = None
        _robots[base] = rp
    rp = _robots[base]
    return True if rp is None else rp.can_fetch(UA, url)

def looks_like_challenge(text: str) -> bool:
    return bool(CHALLENGE.search(text[:4000]))

def polite_get(url: str, **kw):
    global _last
    wait = DELAY_SECONDS - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.time()
    return requests.get(url, headers={"User-Agent": UA}, timeout=30, **kw)

def classify_pdf(url: str, text: str):
    """Guess document kind, year and exam session from the link text and URL only."""
    blob = f"{url} {text}"
    kind = "answer_key" if re.search(r"answer|key", blob, re.I) else "question_paper"
    m = re.search(r"(20\d{2}|19\d{2})", blob)
    session = None
    s = re.search(r"session[\s_-]*([12])", blob, re.I)
    if s: session = s.group(1)
    shift = None
    sh = re.search(r"shift[\s_-]*([12])", blob, re.I)
    if sh: shift = sh.group(1)
    return {"doc_kind": kind, "exam_year": int(m.group(1)) if m else None, "session": session, "shift": shift}

def discover(log):
    """Yield dicts describing candidate PDFs. `log(level, message, details)` records problems."""
    found = {}
    for src in SOURCES:
        start = src["start"]
        if not allowed(start):
            log("warn", f"robots.txt disallows {start}; skipped", {}); continue
        try:
            r = polite_get(start)
        except requests.RequestException as e:
            log("error", f"Could not reach {start}: {e}", {}); continue
        if r.status_code != 200 or looks_like_challenge(r.text):
            log("warn", f"{start} did not return a normal page (status {r.status_code}); not bypassing", {}); continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            url = urljoin(start, a["href"])
            label = a.get_text(" ", strip=True)
            if url.lower().split("?")[0].endswith(".pdf") and KEYWORDS.search(f"{url} {label}"):
                found.setdefault(url, {"url": url, "page": start, "exam": src["exam"], "label": label, **classify_pdf(url, label)})
    return list(found.values())
