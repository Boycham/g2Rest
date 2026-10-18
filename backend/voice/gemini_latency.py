"""Time the Gemini intent call: the old request body against the current one.

    GEMINI_API_KEY=... .venv/bin/python gemini_latency.py [n]

Same model, endpoint and ?key= for both, so only the body differs. Prints milliseconds per call and
the median; the key is never printed.
"""

from __future__ import annotations

import os
import statistics
import sys
import time

import httpx

from gemini_intent import GEMINI_MODEL, GEMINI_URL, INSTRUCTIONS, SCHEMA, request_body

PHRASES = ["give it to ben", "i'll take it", "pass on this one", "show me the list", "undo that"]


def old_body(words: str) -> dict[str, object]:
    """The body before this change: one interpolated prompt, default thinking."""
    prompt = f'{INSTRUCTIONS}\nThe words: "{words}"'
    return {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA,
            "temperature": 0,
        },
    }


def run(name: str, make, n: int, key: str) -> None:
    times = []
    with httpx.Client(timeout=15) as http:
        for i in range(n):
            words = PHRASES[i % len(PHRASES)]
            t = time.perf_counter()
            r = http.post(
                GEMINI_URL.format(model=GEMINI_MODEL), params={"key": key}, json=make(words)
            )
            ms = (time.perf_counter() - t) * 1000
            times.append(ms)
            usage = r.json().get("usageMetadata", {}) if r.status_code == 200 else {}
            print(
                f"{name} {i + 1}: {ms:.0f} ms, HTTP {r.status_code}, prompt tokens "
                f"{usage.get('promptTokenCount')}, thinking tokens {usage.get('thoughtsTokenCount', 0)}"
            )
    print(f"{name} median of {n}: {statistics.median(times):.0f} ms")


if __name__ == "__main__":
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        sys.exit("set GEMINI_API_KEY")
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    print(f"model {GEMINI_MODEL}")
    run("before", old_body, count, api_key)
    run("after", request_body, count, api_key)
