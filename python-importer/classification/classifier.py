"""Provider-agnostic classifier. Keys come only from environment variables (GitHub Secrets in CI)."""
import json, os
import requests

PROVIDERS = {
    "gemini": {"key": "GEMINI_API_KEY"},
    "openrouter": {"key": "OPENROUTER_API_KEY", "base": "https://openrouter.ai/api/v1", "model": "OPENROUTER_MODEL"},
    "openai_compatible": {"key": "OPENAI_COMPAT_API_KEY", "base": "OPENAI_COMPAT_BASE_URL", "model": "OPENAI_COMPAT_MODEL"},
}
LOW_CONFIDENCE = 0.75

def configured(provider: str) -> bool:
    p = PROVIDERS.get(provider)
    return bool(p and os.environ.get(p["key"]))

def prompt(statement: str, taxonomy: dict) -> str:
    return ("Classify this JEE question. Reply with JSON only: "
            '{"subject":"physics|chemistry|mathematics","chapter":"<exact name from list>","topic":"<exact name or null>","difficulty":"easy|medium|hard","confidence":0.0-1.0}. '
            "Use only chapter names from the taxonomy. Do not solve the question.\n"
            f"Taxonomy: {json.dumps(taxonomy)}\nQuestion: {statement[:3000]}")

def _call(provider: str, text: str) -> str:
    p = PROVIDERS[provider]; key = os.environ[p["key"]]
    if provider == "gemini":
        model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", headers={"x-goog-api-key": key},
                          json={"contents": [{"parts": [{"text": text}]}], "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}, timeout=60)
        r.raise_for_status(); return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    base = p["base"] if provider == "openrouter" else os.environ[p["base"]]
    model = os.environ.get(p["model"], "")
    r = requests.post(base.rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {key}"},
                      json={"model": model, "temperature": 0, "messages": [{"role": "user", "content": text}]}, timeout=60)
    r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]

def parse_reply(raw: str) -> dict | None:
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    if d.get("difficulty") not in ("easy", "medium", "hard"):
        d["difficulty"] = None
    if not isinstance(d, dict):
        return None
    try:
        d["confidence"] = max(0.0, min(1.0, float(d.get("confidence") or 0)))
    except (TypeError, ValueError):
        d["confidence"] = 0.0
    return d

def classify(provider: str, statement: str, taxonomy: dict) -> dict | None:
    out = parse_reply(_call(provider, prompt(statement, taxonomy)))
    if out: out["needs_review"] = out["confidence"] < LOW_CONFIDENCE
    return out
