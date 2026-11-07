"""Polite, bounded crawler for the official JEE sites.

Hard rules (enforced here, not left to callers):
  * robots.txt is read and obeyed for every host, including Crawl-delay.
  * At least `delay` seconds between requests to the same host.
  * CAPTCHA, login walls, bot challenges and HTTP 403/429 are recorded and respected. The crawler does not retry
    with different headers, does not rotate agents and does not try to solve anything. After `block_limit` refusals
    a host is dropped for the rest of the run.
  * Only the seed hosts are crawled. Links to other sites are logged and ignored.
Every link decision is reported through `log(level, message, details)` with a machine-readable `reason`.
"""
from __future__ import annotations
import re
import time
import urllib.robotparser
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from sources.metadata import classify_document, detect_exam, file_stem

UA = "JEE-PYQ-Studio-Importer/2.0 (personal study tool; obeys robots.txt; no CAPTCHA or login bypass)"
DEFAULT_DELAY = 3.0
MAX_HTML_BYTES = 3_000_000

@dataclass(frozen=True)
class Seed:
    exam: str | None            # None = decide per link (shared hosts such as nta.ac.in)
    start: str
    host: str                   # registrable host that may be crawled
    require_jee: bool = False   # on shared hosts, only follow/accept links that mention JEE

SEEDS = [
    Seed("jee_main", "https://jeemain.nta.nic.in/", "jeemain.nta.nic.in"),
    Seed("jee_main", "https://www.nta.ac.in/", "nta.ac.in", require_jee=True),
    Seed("jee_advanced", "https://jeeadv.ac.in/", "jeeadv.ac.in"),
]

FOLLOW_HINT = re.compile(r"archive|previous[\s_-]*year|past[\s_-]*(?:year|paper)|question[\s_-]*paper|\bpapers?\b|answer[\s_-]*key|final[\s_-]*key|"
                         r"provisional|download|pyq|\bqps?\b|(?:19|20)\d{2}|session|shift", re.I)
NEVER_FOLLOW = re.compile(r"login|log-in|signin|sign-in|register|registration|captcha|logout|apply[\s_-]*online|payment|candidate[\s_-]*(?:login|portal)|"
                          r"\.(?:jpe?g|png|gif|svg|webp|ico|css|js|zip|rar|docx?|xlsx?|pptx?|mp4|mp3)(?:$|\?)", re.I)
HTML_OK = re.compile(r"(?:\.(?:html?|php|aspx?|jsp)(?:$|\?))|(?:/[^./]*(?:/|$|\?))", re.I)
PDF_EXT = re.compile(r"\.pdf(?:$|[?#])", re.I)
DOWNLOAD_ENDPOINT = re.compile(r"/(?:download|getfile|viewfile|file|attachment|document)s?(?:/|\?|$)|[?&](?:file|doc|download)=", re.I)
CHALLENGE = re.compile(r"captcha|are you (?:a )?(?:robot|human)|verify you are (?:a )?human|access denied|attention required|just a moment|"
                       r"cf-chl|checking your browser|request unsuccessful|incapsula|akamai.{0,40}reference", re.I)


@dataclass
class FetchResult:
    ok: bool
    url: str
    status: int | None = None
    reason: str = "ok"          # ok | robots_disallowed | blocked | rate_limited | challenge_page | login_wall | network_error | http_error | not_html | too_large | host_dropped
    message: str = ""
    content: bytes = b""
    content_type: str = ""

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


@dataclass
class FoundDocument:
    url: str
    page_url: str
    exam: str | None
    link_text: str
    context: str
    depth: int
    meta: dict
    skip_reason: str | None = None


@dataclass
class CrawlResult:
    documents: list[FoundDocument] = field(default_factory=list)
    pages_visited: int = 0
    failures: list[dict] = field(default_factory=list)       # {"url","reason","message"}
    seeds_reached: int = 0
    seeds_total: int = 0


def looks_like_challenge(text: str) -> bool:
    return bool(CHALLENGE.search((text or "")[:6000]))


def looks_like_login_wall(html: str) -> bool:
    soup = BeautifulSoup(html[:200_000], "html.parser")
    has_pw = bool(soup.find("input", {"type": "password"}))
    text = soup.get_text(" ", strip=True)
    return has_pw and len(text) < 1500 and bool(re.search(r"log\s*in|sign\s*in", text, re.I))


def normalise_url(url: str) -> str:
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    return p._replace(netloc=p.netloc.lower(), scheme=p.scheme.lower()).geturl()


class Fetcher:
    """HTTP with robots.txt, per-host rate limiting and refusal detection. `sleep`/`clock` are injectable for tests."""

    def __init__(self, delay: float = DEFAULT_DELAY, session=None, sleep=time.sleep, clock=time.time, block_limit: int = 3, timeout: int = 30):
        self.delay, self.http, self.sleep, self.clock = delay, session or requests.Session(), sleep, clock
        self.block_limit, self.timeout = block_limit, timeout
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last: dict[str, float] = {}
        self._blocks: dict[str, int] = {}
        self.http.headers["User-Agent"] = UA

    # --- robots.txt -----------------------------------------------------------------------------------------
    def _robots_for(self, base: str):
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                self._wait(base)
                r = self.http.get(base + "/robots.txt", timeout=self.timeout)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                elif r.status_code in (401, 403):
                    rp.disallow_all = True       # robots.txt itself refused: treat the site as off limits
                else:
                    rp.allow_all = True          # no robots.txt: nothing disallowed
            except requests.RequestException:
                rp = None                         # unreachable: the page fetch will report the real error
            self._robots[base] = rp
        return self._robots[base]

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        rp = self._robots_for(f"{p.scheme}://{p.netloc}")
        return True if rp is None else rp.can_fetch(UA, url)

    def _crawl_delay(self, base: str) -> float:
        rp = self._robots.get(base)
        try:
            d = rp.crawl_delay(UA) if rp else None
        except Exception:
            d = None
        return max(self.delay, float(d)) if d else self.delay

    def _wait(self, base: str):
        wait = self._crawl_delay(base) - (self.clock() - self._last.get(base, 0.0))
        if wait > 0:
            self.sleep(wait)
        self._last[base] = self.clock()

    def host_dropped(self, host: str) -> bool:
        return self._blocks.get(host, 0) >= self.block_limit

    # --- fetching -------------------------------------------------------------------------------------------
    def get(self, url: str, expect: str = "html", max_bytes: int | None = None) -> FetchResult:
        p = urlparse(url)
        base, host = f"{p.scheme}://{p.netloc}", p.netloc.lower()
        if self.host_dropped(host):
            return FetchResult(False, url, None, "host_dropped", f"{host} refused automated access {self._blocks[host]} times; skipped for this run")
        if not self.allowed(url):
            return FetchResult(False, url, None, "robots_disallowed", "robots.txt disallows this URL for automated clients")
        self._wait(base)
        try:
            r = self.http.get(url, timeout=self.timeout, stream=True)
        except requests.RequestException as e:
            return FetchResult(False, url, None, "network_error", f"{type(e).__name__}: {e}")
        status, ctype = r.status_code, r.headers.get("Content-Type", "").lower()
        if status in (403, 429, 503) and (status != 503 or looks_like_challenge(r.text[:6000])):
            self._blocks[host] = self._blocks.get(host, 0) + 1
            reason = "rate_limited" if status == 429 else "blocked"
            return FetchResult(False, url, status, reason, f"HTTP {status}: the site refuses automated access. Not bypassed. Download the PDF yourself and use Manual upload in Admin.")
        if status >= 400:
            return FetchResult(False, url, status, "http_error", f"HTTP {status}")
        limit = max_bytes or (MAX_HTML_BYTES if expect == "html" else 80_000_000)
        body = b""
        for chunk in r.iter_content(65536):
            body += chunk
            if len(body) > limit:
                r.close()
                return FetchResult(False, url, status, "too_large", f"response larger than {limit // 1_000_000} MB")
        if expect == "html":
            if "html" not in ctype and "xml" not in ctype and not body[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
                return FetchResult(False, url, status, "not_html", f"content type {ctype or 'unknown'}")
            txt = body.decode("utf-8", errors="replace")
            if looks_like_challenge(txt):
                self._blocks[host] = self._blocks.get(host, 0) + 1
                return FetchResult(False, url, status, "challenge_page", "page looks like a CAPTCHA or bot challenge; not bypassed")
            if looks_like_login_wall(txt):
                return FetchResult(False, url, status, "login_wall", "page requires a login; not bypassed")
        return FetchResult(True, url, status, "ok", "", body, ctype)

    def head_is_pdf(self, url: str) -> bool:
        p = urlparse(url)
        if self.host_dropped(p.netloc.lower()) or not self.allowed(url):
            return False
        self._wait(f"{p.scheme}://{p.netloc}")
        try:
            r = self.http.head(url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException:
            return False
        return r.status_code == 200 and "pdf" in r.headers.get("Content-Type", "").lower()


# ----------------------------------------------------------------------------------------------------------------------
# Page parsing (pure)
# ----------------------------------------------------------------------------------------------------------------------
def _context_for(a) -> str:
    """Nearby text for a link: its table row or list item, plus the closest preceding heading/bold label."""
    parts = []
    row = a.find_parent(["tr", "li", "p", "div"])
    if row is not None:
        txt = row.get_text(" ", strip=True)
        if len(txt) <= 300:
            parts.append(txt)
    for prev in a.find_all_previous(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "th", "caption"], limit=3):
        t = prev.get_text(" ", strip=True)
        if t and len(t) < 120:
            parts.append(t)
            break
    return " | ".join(parts)


def _page_hint(soup) -> str:
    bits = [soup.title.get_text(" ", strip=True) if soup.title else ""]
    h = soup.find(["h1", "h2"])
    if h:
        bits.append(h.get_text(" ", strip=True))
    return " ".join(b for b in bits if b)[:300]


def extract_links(html: str, page_url: str) -> tuple[list[dict], list[dict], str]:
    """Returns (pdf_links, page_links, page_hint). Each link: {url, text, context, maybe_pdf}."""
    soup = BeautifulSoup(html, "html.parser")
    pdfs, pages, seen = [], [], set()
    hint = _page_hint(soup)

    def add(url, text, ctx, el):
        url = normalise_url(urljoin(page_url, url))
        if not url.startswith(("http://", "https://")) or url in seen:
            return
        seen.add(url)
        rec = {"url": url, "text": text, "context": ctx}
        if PDF_EXT.search(url):
            pdfs.append(rec)
        elif DOWNLOAD_ENDPOINT.search(url):
            pdfs.append({**rec, "maybe_pdf": True})
        else:
            pages.append(rec)

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith(("mailto:", "tel:", "javascript:", "#")):
            m = re.search(r"""['"]([^'"]+\.pdf[^'"]*)['"]""", a.get("onclick", "") or href, re.I)
            if m:
                add(m.group(1), a.get_text(" ", strip=True), _context_for(a), a)
            continue
        add(href, a.get_text(" ", strip=True) or a.get("title", ""), _context_for(a), a)
    for tag in soup.find_all(["iframe", "embed", "object"]):
        src = tag.get("src") or tag.get("data")
        if src and PDF_EXT.search(src):
            add(src, tag.get("title", ""), "", tag)
    return pdfs, pages, hint


def follow_decision(url: str, text: str, seed: Seed) -> tuple[bool, str]:
    p = urlparse(url)
    host = p.netloc.lower()
    if not (host == seed.host or host.endswith("." + seed.host)):
        return False, "off_site"
    if NEVER_FOLLOW.search(url) or NEVER_FOLLOW.search(text or ""):
        return False, "login_or_media_link"
    if not HTML_OK.search(p.path + ("?" + p.query if p.query else "")):
        return False, "not_a_web_page"
    blob = f"{url} {text}"
    if seed.require_jee and not re.search(r"\bjee\b", blob, re.I):
        return False, "not_jee_related"
    if not FOLLOW_HINT.search(blob):
        return False, "no_archive_keyword"
    return True, "archive_like"


# ----------------------------------------------------------------------------------------------------------------------
# Crawl
# ----------------------------------------------------------------------------------------------------------------------
def crawl(fetcher: Fetcher, log, seeds=SEEDS, max_depth: int = 3, max_pages_per_seed: int = 60, extra_starts: list[str] | None = None) -> CrawlResult:
    """Breadth-first crawl. `log(level, message, details)` receives every decision."""
    res = CrawlResult(seeds_total=len(seeds))
    found: dict[str, FoundDocument] = {}
    for seed in seeds:
        queue = deque([(seed.start, 0)])
        visited: set[str] = set()
        reached = False
        pages = 0
        while queue and pages < max_pages_per_seed:
            url, depth = queue.popleft()
            url = normalise_url(url)
            if url in visited:
                continue
            visited.add(url)
            r = fetcher.get(url, "html")
            if not r.ok:
                level = "warn" if r.reason in ("blocked", "rate_limited", "challenge_page", "login_wall", "robots_disallowed", "host_dropped") else "error"
                log(level, f"Page not read ({r.reason}): {url} - {r.message}", {"url": url, "reason": r.reason, "status": r.status, "depth": depth, "stage": "discover"})
                res.failures.append({"url": url, "reason": r.reason, "message": r.message})
                if r.reason == "host_dropped":
                    break
                continue
            reached = True
            pages += 1
            res.pages_visited += 1
            pdfs, links, hint = extract_links(r.text, url)
            log("info", f"Read {url}: {len(pdfs)} PDF link(s), {len(links)} other link(s)", {"url": url, "depth": depth, "pdfs": len(pdfs), "stage": "discover"})
            for L in pdfs:
                _register_pdf(fetcher, log, found, seed, L, url, hint, depth)
            for L in links:
                follow, why = follow_decision(L["url"], L["text"], seed)
                if follow and depth < max_depth and L["url"] not in visited:
                    queue.append((L["url"], depth + 1))
                elif follow:
                    log("debug", f"Not followed (depth limit {max_depth}): {L['url']}", {"url": L["url"], "reason": "depth_limit", "stage": "discover"})
                elif why in ("off_site", "login_or_media_link", "not_jee_related"):
                    log("debug", f"Not followed ({why}): {L['url']}", {"url": L["url"], "reason": why, "stage": "discover"})
        if pages >= max_pages_per_seed and queue:
            log("warn", f"Page limit ({max_pages_per_seed}) reached on {seed.host}; {len(queue)} page(s) left unvisited. Raise --max-pages to go further.", {"reason": "page_limit", "stage": "discover"})
        res.seeds_reached += 1 if reached else 0
    res.documents = list(found.values())
    return res


def _register_pdf(fetcher, log, found, seed, L, page_url, hint, depth):
    url = L["url"]
    if url in found:
        return
    if L.get("maybe_pdf") and not fetcher.head_is_pdf(url):
        log("debug", f"Download-style link is not a PDF, ignored: {url}", {"url": url, "reason": "not_a_pdf", "stage": "discover"})
        return
    exam = seed.exam if seed.exam and not seed.require_jee else detect_exam(url, f"{L['text']} {L['context']} {hint}")
    meta = classify_document(url, L["text"], L["context"], hint)
    skip = None
    if seed.require_jee and not re.search(r"\bjee\b", f"{url} {L['text']} {L['context']}", re.I):
        skip = "not a JEE document (shared NTA site)"
    elif exam is None:
        skip = "could not tell which exam this belongs to"
    elif meta["skip_reason"]:
        skip = meta["skip_reason"]
    elif meta["doc_kind"] == "solution":
        skip = "solutions document: solutions and answers are never imported automatically"
    doc = FoundDocument(url, page_url, exam, L["text"], L["context"], depth, meta, skip)
    found[url] = doc
    if skip:
        log("info", f"PDF discovered but skipped: {file_stem(url)} - {skip}", {"url": url, "page": page_url, "reason": "skipped_by_classifier", "detail": skip, "stage": "discover"})
    else:
        log("info", f"PDF discovered: {file_stem(url)} [{meta['doc_kind']}, year={meta['exam_year']}, session={meta['session']}, shift={meta['shift']}, paper={meta['paper_number']}]",
            {"url": url, "page": page_url, "stage": "discover", "evidence": meta["evidence"]})
