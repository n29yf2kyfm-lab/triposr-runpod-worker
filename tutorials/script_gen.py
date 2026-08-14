"""Turn a human-verified procedure template into a timed narration script.

The mechanical content comes ONLY from the YAML template (see
procedures/*.yaml — the accuracy contract). An LLM may optionally reword
narration for flow/tone (LLM_PROVIDER env), but the default path is fully
deterministic so the request path has zero required API dependencies and
tests run offline.
"""
import os
import re
from pathlib import Path

import yaml

PROCEDURES_DIR = Path(os.environ.get(
    "PROCEDURES_DIR", Path(__file__).resolve().parent / "procedures"
))

# Planning estimate only — final timing comes from the real TTS audio.
WORDS_PER_SECOND = 2.6
MIN_STEP_SECONDS = 3.0


class _SafeDict(dict):
    def __missing__(self, key):  # leave unknown {placeholders} visible
        return "{" + key + "}"


def list_procedures():
    return sorted(p.stem for p in PROCEDURES_DIR.glob("*.yaml"))


def load_procedure(procedure_id):
    if not re.fullmatch(r"[a-z0-9_]+", procedure_id or ""):
        raise ValueError(f"Invalid procedure id: {procedure_id!r}")
    path = PROCEDURES_DIR / f"{procedure_id}.yaml"
    if not path.exists():
        raise ValueError(
            f"Unknown procedure '{procedure_id}'. Available: {list_procedures()}"
        )
    with open(path) as f:
        proc = yaml.safe_load(f)
    for field in ("id", "title", "steps"):
        if not proc.get(field):
            raise ValueError(f"Template {path.name} missing '{field}'")
    return proc


def _fill(text, variables):
    return text.format_map(_SafeDict(variables)).strip()


def estimate_seconds(text):
    return max(MIN_STEP_SECONDS, len(text.split()) / WORDS_PER_SECOND)


def build_script(procedure_id, vehicle=None, overrides=None):
    """Returns {title, disclaimer, steps: [{id, title, narration, broll,
    card, est_seconds}], est_total_seconds}."""
    proc = load_procedure(procedure_id)
    variables = dict(proc.get("vehicle_defaults") or {})
    if vehicle:
        variables["vehicle"] = vehicle
    variables.update(overrides or {})

    steps = []
    for raw in proc["steps"]:
        narration = _fill(raw["narration"], variables)
        steps.append({
            "id": raw["id"],
            "title": _fill(raw["title"], variables),
            "narration": narration,
            "broll": raw.get("broll", ""),
            "card": [_fill(line, variables) for line in raw.get("card", [])],
            "est_seconds": round(estimate_seconds(narration), 1),
        })

    title = _fill(proc["title"], variables)
    if vehicle:
        title = f"{title} — {vehicle}"
    return {
        "procedure_id": proc["id"],
        "title": title,
        "disclaimer": (proc.get("disclaimer") or "").strip(),
        "tools": proc.get("tools", []),
        "safety_critical": bool(proc.get("safety_critical")),
        "steps": steps,
        "est_total_seconds": round(sum(s["est_seconds"] for s in steps), 1),
    }


def polish_narration(script, provider=None):
    """Optionally reword narration with an LLM for flow. Mechanical content
    must not change — the prompt forbids adding/removing facts, and any
    failure returns the script unchanged (deterministic text is always an
    acceptable output)."""
    provider = provider or os.environ.get("LLM_PROVIDER", "")
    if not provider:
        return script
    try:
        if provider == "anthropic":
            return _polish_anthropic(script)
        if provider == "gemini":
            return _polish_gemini(script)
        print(f"unknown LLM_PROVIDER {provider!r}; skipping polish")
    except Exception as e:
        print(f"polish failed ({type(e).__name__}: {e}); using template narration")
    return script


_POLISH_INSTRUCTION = (
    "Reword each narration line for a friendly 60-second video tutorial "
    "voiceover. Keep EVERY technical fact, warning, order of steps and "
    "number exactly as given; do not add or remove any instruction. Return "
    "one line per input line, same order, no numbering."
)


def _polish_lines(script):
    return [s["narration"] for s in script["steps"]]


def _apply_lines(script, lines):
    if len(lines) == len(script["steps"]):
        for step, line in zip(script["steps"], lines):
            if line.strip():
                step["narration"] = line.strip()
    return script


def _polish_anthropic(script):
    import requests
    lines = _polish_lines(script)
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
            "max_tokens": 2048,
            "messages": [{
                "role": "user",
                "content": _POLISH_INSTRUCTION + "\n\n" + "\n".join(lines),
            }],
        },
        timeout=60,
    )
    r.raise_for_status()
    text = r.json()["content"][0]["text"]
    return _apply_lines(script, [l for l in text.splitlines() if l.strip()])


def _polish_gemini(script):
    import requests
    lines = _polish_lines(script)
    model = os.environ.get("GEMINI_MODEL", "gemini-3.7-flash")
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": os.environ["GEMINI_API_KEY"]},
        json={"contents": [{"parts": [{
            "text": _POLISH_INSTRUCTION + "\n\n" + "\n".join(lines),
        }]}]},
        timeout=60,
    )
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return _apply_lines(script, [l for l in text.splitlines() if l.strip()])
