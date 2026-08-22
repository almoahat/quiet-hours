"""Stage 3: Diagnose.

The ONLY LLM call in the pipeline. Renders the incident window into compact
text, sends it with the hand-written prompt from prompts/diagnose.txt, and
parses the response into a Diagnosis. Talks to any OpenAI-compatible
endpoint (Ollama locally by default) via LLM_URL / LLM_MODEL.

On malformed JSON or a failed validate() check, retries once with the
problems appended to the conversation, then gives up cleanly (returns None)
rather than looping forever or fabricating a result.
"""

import json
import os
import sys
from pathlib import Path

from openai import OpenAI

from quiet_hours.contracts import Claim, Diagnosis, IncidentWindow
from quiet_hours.validate import validate

PROMPT_PATH = Path(__file__).parent / "prompts" / "diagnose.txt"
MAX_ATTEMPTS = 2


def render_window(window: IncidentWindow) -> str:
    """Compact, LLM-friendly text rendering of the incident window.

    Deliberately withholds two things the model must work out for itself:
      - window.trigger, which names the root-cause event_id and quotes its
        message -- rendering it would hand the model the answer. It stays
        on the IncidentWindow object for logging and the UI.
      - stats.by_host, which is dozens of near-unique pod names that burn
        context without helping. Only a distinct-host count is rendered;
        the full breakdown stays on the IncidentWindow object. by_service
        and by_source, being small and directly informative, are kept.
    """
    stats = window.stats
    compact_stats = {
        "total": stats["total"],
        "by_source": stats["by_source"],
        "by_service": stats["by_service"],
        "by_level": stats["by_level"],
        "distinct_hosts": len(stats["by_host"]),
    }
    header = f"Incident window: {window.start.isoformat()} .. {window.end.isoformat()}\nStats: {compact_stats}\n---"
    lines = [
        f"[{e.event_id}] {e.ts.isoformat()} {e.source} {e.service}@{e.host} {e.level}: {e.message}"
        for e in window.events
    ]
    return "\n".join([header, *lines])


def _client() -> OpenAI:
    base_url = os.environ.get("LLM_URL", "http://localhost:11434/v1")
    api_key = os.environ.get("LLM_API_KEY", "ollama")  # OpenAI-compatible servers usually ignore this
    return OpenAI(base_url=base_url, api_key=api_key)


def _model() -> str:
    model = os.environ.get("LLM_MODEL")
    if not model:
        raise RuntimeError("LLM_MODEL env var is not set")
    return model


def _load_prompt() -> str:
    """Load the Stage 3 system prompt. Raises rather than silently sending
    the model an empty (or missing) system prompt.
    """
    if not PROMPT_PATH.exists():
        raise RuntimeError(
            f"Diagnosis prompt has not been written yet: {PROMPT_PATH} does not exist. "
            "Write the Stage 3 prompt before calling diagnose()."
        )
    text = PROMPT_PATH.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(
            f"Diagnosis prompt has not been written yet: {PROMPT_PATH} is empty. "
            "Write the Stage 3 prompt before calling diagnose()."
        )
    return text


def _parse_diagnosis(raw: str) -> Diagnosis:
    """Parse the model's JSON response into a Diagnosis. Raises on any
    structural problem so the caller can fold it into a retry.
    """
    data = json.loads(raw)
    claims = [Claim(statement=c["statement"], evidence=list(c["evidence"])) for c in data["claims"]]
    return Diagnosis(
        outcome=data["outcome"],
        root_cause=data.get("root_cause"),
        confidence=data["confidence"],
        claims=claims,
        unexplained=list(data.get("unexplained", [])),
    )


def diagnose(window: IncidentWindow) -> Diagnosis | None:
    system_prompt = _load_prompt()  # raises before touching the client if not written yet
    client = _client()
    model = _model()

    window_text = render_window(window)
    if os.environ.get("QH_DEBUG") == "1":
        print("=== QH_DEBUG: rendered incident window ===", file=sys.stderr)
        print(window_text, file=sys.stderr)
        print("=== end QH_DEBUG ===", file=sys.stderr)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": window_text},
    ]

    for attempt in range(MAX_ATTEMPTS):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content

        try:
            diagnosis = _parse_diagnosis(raw)
            errors = validate(diagnosis, window)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            diagnosis = None
            errors = [f"response was not valid JSON matching the Diagnosis schema: {exc}"]

        if diagnosis is not None and not errors:
            return diagnosis

        is_last_attempt = attempt == MAX_ATTEMPTS - 1
        if not is_last_attempt:
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response had problems:\n"
                        + "\n".join(f"- {e}" for e in errors)
                        + "\nReturn corrected strict JSON only, matching the same schema."
                    ),
                }
            )

    return None
