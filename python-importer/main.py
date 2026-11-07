"""Importer entry point (run by GitHub Actions; needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY).

    python main.py                         full run: discover, download, extract, classify, match
    python main.py --mode discover_only    only find and register PDFs
    python main.py --mode process_only     only process already-downloaded/uploaded PDFs
    python main.py --mode retry_failed     download + process documents re-queued from Admin
    python main.py --only-if-queued        exit quietly unless Admin queued a run (used by the frequent poll job)
    python main.py --print-only            crawl and print what would be found; no database, no downloads
"""
import argparse
import os
import re
import sys

from classification.classifier import classify, configured
from pipeline import Config, Pipeline
from sources.crawler import SEEDS, Fetcher, crawl
from store import MemoryStore, SupabaseStore


def build_classifier():
    provider = os.environ.get("AI_PROVIDER", "gemini")
    if not configured(provider):
        print(f"AI provider '{provider}' is not configured: questions will be stored with subject only (no chapter/difficulty).")
        return None
    return lambda statement, taxonomy: classify(provider, statement, taxonomy)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["full", "discover_only", "process_only", "retry_failed"], default=os.environ.get("IMPORT_MODE") or "full")
    ap.add_argument("--max-depth", type=int, default=int(os.environ.get("IMPORT_MAX_DEPTH") or 3))
    ap.add_argument("--max-pages", type=int, default=int(os.environ.get("IMPORT_MAX_PAGES") or 60))
    ap.add_argument("--max-downloads", type=int, default=int(os.environ.get("IMPORT_MAX_DOWNLOADS") or 80))
    ap.add_argument("--delay", type=float, default=float(os.environ.get("IMPORT_DELAY") or 3.0), help="seconds between requests to one host (never below robots.txt Crawl-delay)")
    ap.add_argument("--document-id", default=os.environ.get("IMPORT_DOCUMENT_ID") or None)
    ap.add_argument("--only-if-queued", action="store_true", default=bool(os.environ.get("IMPORT_ONLY_IF_QUEUED")))
    ap.add_argument("--print-only", action="store_true")
    a = ap.parse_args(argv)
    if a.document_id and not re.fullmatch(r"[0-9a-fA-F-]{36}", a.document_id):
        ap.error("--document-id must be a document UUID")

    fetcher = Fetcher(delay=max(a.delay, 1.0))
    if a.print_only:
        res = crawl(fetcher, lambda lvl, msg, d=None: print(f"[{lvl}] {msg}"), max_depth=a.max_depth, max_pages_per_seed=a.max_pages)
        print(f"\n{res.pages_visited} page(s) read, {len(res.documents)} PDF link(s), {len(res.failures)} page failure(s).")
        return 0 if res.seeds_reached else 3
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required (GitHub Secrets).", file=sys.stderr)
        return 2
    store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    trigger = "schedule" if os.environ.get("GITHUB_EVENT_NAME") == "schedule" else "manual"
    p = Pipeline(store, fetcher, build_classifier(), Config(a.mode, a.max_depth, a.max_pages, a.max_downloads, a.document_id, a.only_if_queued, a.delay), trigger)
    p.run()
    code = getattr(p, "outcome", "ok")
    if code == "sources_unreachable":
        print("::error::None of the official sites could be read. Nothing was imported. See the run summary and Admin > Import logs.")
        return 3
    if code in ("partial_failures", "nothing_discovered"):
        print(f"::warning::Import finished with outcome '{code}'. See Admin > Documents for reasons.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
