"""Two-table clip test (dev only): does a neighbouring table's order leak into ours?

    ELEVENLABS_AGENT_ID=... python clip_test.py [--bg-db -10] [--runs 5]

Builds a ~20 s order clip at our table (server and two guests, near) with a second table
ordering other dishes behind it (two other voices, 'far': low-passed with early reflections,
--bg-db below our table's speech level). Each run goes through RelaySession exactly like a
swipe-back clip, with the live batch Scribe and clip agent:
- before: diarized transcript with speaker labels, every speaker kept (main);
- after: + menu/staff keyterms, quieter speakers dropped (voice_session.other_tables).
Reports how often the other table's dishes reach the draft, our dishes found, and the clip
latency (capture.stop -> draft). Only the TTS inputs are cached, in the gitignored fixtures/.
"""

from __future__ import annotations

import argparse
import array
import asyncio
import json
import statistics
import time
from typing import Any

import httpx

from commands import keyterms
from make_fixtures import GUEST_VOICE, SERVER_VOICE, tts
from noise_test import active_dbfs, cached, clamp, far, scaled
from relay import RelaySession, live_agent
from voice_session import API, FRAME_BYTES, api_key, clip_turns, log, scribe_batch, speaker_levels

SR = 16000
GUEST2_VOICE = "nPczCjzI2devNBz1zQrb"  # Brian (premade)
NEIGHBOUR_VOICES = ("TX3LPaxmHKxFdv7VOQHJ", "XrExE9yKIg1WjnnlVkGX")  # Liam, Matilda (premade)
TABLE = [
    (SERVER_VOICE, "Good evening. Are we ready to order?"),
    (GUEST_VOICE, "Yes. I'll have the halibut, but no butter please."),
    (SERVER_VOICE, "Of course. And for you, sir?"),
    (GUEST2_VOICE, "The salmon for me. I have a shellfish allergy."),
    (SERVER_VOICE, "Noted. Anything to start?"),
    (GUEST_VOICE, "Let's share the burrata."),
    (SERVER_VOICE, "Perfect. I'll get that started for you."),
]
NEIGHBOURS = [
    (0, "Can we get the ribeye, medium rare?"),
    (1, "And I'll do the duck breast, please."),
    (0, "Oh, and the pork belly to start."),
    (1, "And the mushroom risotto for the table."),
]
OURS = {"halibut", "salmon", "burrata salad"}  # draft labels: first menu alias
THEIRS = {"ribeye", "duck", "pork belly", "risotto"}


def track(
    http: httpx.Client, lines, tag: str, gap: float, levels, start: float = 0.0
) -> list[float]:
    """Lines one after another, each normalised to its active-speech level in dBFS."""
    out: list[float] = [0.0] * int(start * SR)
    for n, ((voice, text), db) in enumerate(zip(lines, levels, strict=True)):
        pcm = cached(f"clip2_{tag}{n}.pcm", lambda v=voice, t=text: tts(http, v, t))
        out += list(scaled(pcm, db - active_dbfs(pcm))) + [0.0] * int(gap * SR)
    return out


def two_table_clip(bg_db: float, wearer_db: float) -> bytes:
    """Our table's guests at -20 dBFS, the wearer `wearer_db` above them, the neighbours
    `bg_db` below them and 'far'."""
    with httpx.Client(base_url=API, headers={"xi-api-key": api_key()}, timeout=60) as http:
        ours = track(
            http, TABLE, "t", 0.7, [-20 + (wearer_db if v == SERVER_VOICE else 0) for v, _ in TABLE]
        )
        lines = [(NEIGHBOUR_VOICES[v], t) for v, t in NEIGHBOURS]
        theirs = far(
            array.array(
                "h",
                (
                    clamp(x)
                    for x in track(http, lines, "n", 1.6, [-20 + bg_db] * len(lines), start=1.5)
                ),
            )
        )
    n = max(len(ours), len(theirs))
    mix = (
        (ours[i] if i < len(ours) else 0) + (theirs[i] if i < len(theirs) else 0) for i in range(n)
    )  # fmt: skip
    return array.array("h", (clamp(x) for x in mix)).tobytes()


async def run_once(pcm: bytes, after: bool) -> dict[str, Any]:
    sent: list[dict[str, Any]] = []
    info: dict[str, Any] = {}

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    async def transcribe(clip: bytes) -> list[tuple[str, str]]:
        t0 = time.monotonic()
        body = await scribe_batch(clip, keyterms=keyterms(realtime=False) if after else ())
        turns, dropped = clip_turns(body, clip, drop_other_tables=after)
        info["stt"] = time.monotonic() - t0
        levels = speaker_levels(body.get("words") or [], clip)
        info["speakers"] = {s: (n, round(db, 1)) for s, (n, db) in levels.items()}
        info["dropped"] = sorted(dropped)
        info["turns"] = turns
        return turns

    session = RelaySession(send, lambda p, c: None, live_agent, transcribe)  # type: ignore[arg-type,return-value]
    await session.handle_text(
        json.dumps({"type": "capture.start", "captureId": "c", "mode": "clip", "table": "T3"})
    )
    for i in range(0, len(pcm), FRAME_BYTES):
        await session.audio(pcm[i : i + FRAME_BYTES])
    n0 = len(sent)
    t0 = time.monotonic()
    await session.handle_text('{"type": "capture.stop", "captureId": "c"}')
    while time.monotonic() - t0 < 60:
        done = [m for m in sent[n0:] if m.get("voice") in ("idle", "offline") and "lines" in m]
        if done:
            break
        await asyncio.sleep(0.05)
    info["total"] = time.monotonic() - t0
    await session.close()
    draft = sent[-1] if sent else {}
    dishes = {ln["dish"] for ln in draft.get("lines", [])}
    info["dishes"] = sorted(dishes)
    info["leaked"] = sorted(dishes & THEIRS)
    info["ours"] = sorted(dishes & OURS)
    return info


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bg-db", type=float, default=-10.0)
    ap.add_argument("--wearer-db", type=float, default=0.0, help="server above the guests")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--only", choices=("before", "after"))
    args = ap.parse_args()
    pcm = two_table_clip(args.bg_db, args.wearer_db)
    log(f"two-table clip {len(pcm) / 32000:.1f} s, neighbours at {args.bg_db:+.0f} dB, "
        f"wearer at {args.wearer_db:+.0f} dB")  # fmt: skip
    summary: dict[str, Any] = {"bg_db": args.bg_db, "wearer_db": args.wearer_db}
    for after in (False, True):
        tag = "after" if after else "before"
        if args.only and args.only != tag:
            continue
        runs = []
        for r in range(args.runs):
            info = await run_once(pcm, after)
            runs.append(info)
            print(f"[{tag} r{r}] dishes {info['dishes']} leaked {info['leaked']} "
                  f"stt {info.get('stt', 0):.2f}s total {info['total']:.2f}s "
                  f"speakers {info.get('speakers')} dropped {info.get('dropped')}")  # fmt: skip
            if r == 0:
                for s, text in info.get("turns", []):
                    print(f"      {s}: {text}")
        summary[tag] = {
            "leak_runs": f"{sum(bool(i['leaked']) for i in runs)}/{len(runs)}",
            "our_dishes": f"{sum(len(i['ours']) for i in runs)}/{len(OURS) * len(runs)}",
            "stt_med": round(statistics.median(i.get("stt", 0) for i in runs), 2),
            "total_med": round(statistics.median(i["total"] for i in runs), 2),
        }
        print(f"[{tag}] {summary[tag]}")
    print("SUMMARY " + json.dumps(summary))


if __name__ == "__main__":
    asyncio.run(main())
