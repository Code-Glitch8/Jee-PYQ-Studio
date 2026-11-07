"""Run statistics and the human-readable summary. Counters are kept separate for question papers and answer keys so an
answer-key document being processed can never look like a successful question-paper import."""
from __future__ import annotations
import os

COUNTERS = [
    ("pages_crawled", "Pages crawled"),
    ("pdfs_discovered", "PDFs discovered"),
    ("pdfs_new", "  of which new"),
    ("question_papers_downloaded", "Question papers downloaded"),
    ("answer_keys_downloaded", "Answer keys downloaded"),
    ("questions_extracted", "Questions extracted"),
    ("questions_classified", "Questions classified (chapter assigned by AI)"),
    ("questions_requiring_review", "Questions requiring review"),
    ("duplicates_skipped", "Duplicate questions skipped"),
    ("answer_entries_extracted", "Answer-key entries extracted"),
    ("answer_entries_proposed", "  matched (awaiting your confirmation)"),
    ("answer_entries_ambiguous", "  ambiguous (manual)"),
    ("answer_entries_unmatched", "  unmatched"),
    ("documents_skipped", "Documents skipped"),
    ("documents_failed", "Documents failed"),
]


class Stats(dict):
    def __missing__(self, key):
        return 0

    def add(self, key, n=1):
        self[key] = self[key] + n


def outcome(stats: Stats, mode: str, seeds_total: int = 0, seeds_reached: int = 0) -> tuple[str, str]:
    """(code, explanation). Never reports success when nothing could be examined."""
    did_discovery = mode in ("full", "discover_only")
    if did_discovery and seeds_total and seeds_reached == 0:
        return "sources_unreachable", ("None of the official sites could be read (blocked, refused or unreachable). "
                                       "Nothing was imported. Use Manual upload in Admin for papers you download yourself.")
    if stats["documents_failed"]:
        return "partial_failures", f"{stats['documents_failed']} document(s) failed; see the reasons in Admin > Documents."
    if did_discovery and stats["pdfs_discovered"] == 0:
        return "nothing_discovered", "The sites were read but no question-paper or answer-key PDF links were found."
    if stats["questions_extracted"] == 0 and stats["answer_entries_extracted"] == 0 and stats["pdfs_new"] == 0:
        return "nothing_new", "No new documents; nothing to import."
    return "ok", ""


def summary(stats: Stats, mode: str, outcome_code: str, explanation: str, by_status: dict | None = None) -> str:
    lines = [f"Import run summary (mode: {mode})", ""]
    lines += [f"{label:<52}{stats[key]:>6}" for key, label in COUNTERS]
    if by_status:
        lines += ["", "All documents by status:"] + [f"  {k:<18}{v:>5}" for k, v in sorted(by_status.items())]
    lines += ["", f"Outcome: {outcome_code}" + (f" - {explanation}" if explanation else "")]
    return "\n".join(lines)


def write_github_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("```\n" + text + "\n```\n")
