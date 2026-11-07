"""Duplicate detection for questions."""
import hashlib, re


def normalise(text: str) -> str:
    t = re.sub(r"\$|\\[a-zA-Z]+|[{}^_]", "", text.lower())
    return re.sub(r"[\W_]+", " ", t).strip()


def fingerprint(statement: str, options: list[dict] | None = None) -> str:
    """Stable id of a question's content: statement plus its options. Same wording in a different layout hashes the same."""
    opts = " | ".join(normalise(o["content"]) for o in (options or []))
    return hashlib.sha256((normalise(statement) + "||" + opts).encode()).hexdigest()


def shingles(text: str, k: int = 3) -> set[str]:
    w = normalise(text).split()
    return {" ".join(w[i:i + k]) for i in range(max(1, len(w) - k + 1))}


def similarity(a: str, b: str) -> float:
    sa, sb = shingles(a), shingles(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def near_duplicates(statement: str, pool: list[tuple[str, str]], threshold: float = 0.88) -> list[tuple[str, float]]:
    """pool: [(question_id, statement)]. Returns [(id, similarity)] at or above the threshold, best first."""
    hits = [(qid, similarity(statement, s)) for qid, s in pool]
    return sorted([h for h in hits if h[1] >= threshold], key=lambda h: -h[1])
