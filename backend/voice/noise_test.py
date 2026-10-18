"""Voice-command crowd test (dev only). Audio stays in memory; only the TTS inputs are cached
in the gitignored fixtures/ folder.

    python noise_test.py [--keyterms] [--vad 0.6] [--gate -35] [--fbg] [--repeat 2]

Streams through realtime Scribe at real-time pace exactly like the relay's command stream
(same ScribeStream options, LoudnessGate and parse_commands):
- recognition: 14 "Verity, <command>." phrases in the 'near' voice (the wearer), 4 s apart,
  over babble at each level. Babble is four 'far' talkers (low-passed, with early
  reflections) talking at once, restaurant and hackathon-hall chatter with command words in it;
- false triggers: the 59 s table conversation, the near-miss phrases (both in the near voice
  at the command's level, the worst case) and the babble alone at every level.
A level is the babble's RMS relative to the command's active-speech RMS (-20 dBFS), so 0 dB is
background talk as loud as the wearer. Every command is scored with the exact parser (main's)
and with sound-alikes on.
"""

from __future__ import annotations

import argparse
import array
import asyncio
import json
import math
import random
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from commands import Command, keyterms, parse_commands
from make_fixtures import SERVER_VOICE, tts
from relay import LoudnessGate
from voice_session import API, FRAME_BYTES, FRAME_SECS, ScribeStream, api_key, frame_dbfs, log

FIX = Path(__file__).with_name("fixtures")
SR = 16000
CMD_DBFS = -20.0
LEVELS = (-12.0, -6.0, -3.0, 0.0, 3.0)  # +3: background louder than the wearer
SPACING = 4.0  # seconds from one command's start to the next
LEAD = 2.0
WINDOW = 3.5  # a command counts if it is heard within this long after its end
PHRASES: list[tuple[str, str, Callable[[Command], bool]]] = [
    (w, f"Verity, {w}.", lambda c, w=w: c.intent == w)
    for w in ("up", "down", "back", "confirm", "clip", "accept", "decline", "done", "revert")
] + [
    ("handoff", "Verity, hand off to Ben.", lambda c: c.intent == "handoff" and c.name == "Ben"),
    ("nevermind", "Verity, never mind.", lambda c: c.intent == "nevermind"),
    ("menu", "Verity, menu.", lambda c: c.intent == "menu"),
    ("queue", "Verity, queue.", lambda c: c.intent == "queue"),
    ("table", "Verity, table four.", lambda c: c.intent == "table" and c.table == 4),
]
NEAR_MISSES = [
    "That was very tasty, thank you.",
    "Could you verify the bill for us?",
    "Verity is my sister's name, actually.",
    "We're done, I accept, let's go back up to the room.",
    "Could we get a table for two by the window?",
    "There's a variety of desserts tonight, all made in house.",
    "Verily, this is the best halibut in town.",
    "The rarity of white truffles makes them pricey.",
    "We need some clarity on the menu, honestly.",
    "I'm very done with this traffic.",
    "Is this a charity dinner? Very good, I'll accept that.",
    "Every table here is booked, so there's a long queue.",
]
# Four other premade voices, so the babble is not the wearer's or the table guest's voice.
BABBLE_VOICES = (
    "CwhRBWXzGAHq8TQ4Fs17",  # Roger
    "FGY2WhTYpPnrIDTdsKH5",  # Laura
    "IKne3meq5aSn9XLyUdCD",  # Charlie
    "cgSgspJ2msm6clMCkdW9",  # Jessica
)
BABBLE = [
    [
        "So our demo is basically done, we just need to clip the video and upload it.",
        "Did you see the team by the back wall? They built a drone that follows you around.",
        "I'm going to grab another coffee, the queue for food is insane right now.",
        "Okay, scroll down, no, back up, there, that's the bug I was talking about.",
        "We should accept the pull request and then revert it if it breaks anything.",
        "Honestly I think the judges care more about the story than the tech.",
    ],
    [
        "Can you pull up the menu? I want to see if they have anything vegetarian.",
        "The salmon was good, but the risotto was a little salty for me.",
        "We need a table for four near the window, we're expecting two more people.",
        "My laptop is at three percent, does anyone have a USB-C charger?",
        "I'll confirm with the organizers, I think the deadline is at nine.",
        "Never mind, I found it, it was in my other bag the whole time.",
    ],
    [
        "Mate, the wifi in here is down again, I can't push anything.",
        "We tried three different models and the small one was the fastest by far.",
        "Is the duck breast any good? I'm thinking of getting the ribeye instead.",
        "Hand me that cable, the long one, thanks. Okay, now it's charging.",
        "Our pitch is two minutes, so we need to cut the intro way down.",
        "I'm done with slides, let's just do a live demo and hope it works.",
    ],
    [
        "Wait, are we presenting in this room or the one upstairs?",
        "I decline every meeting before ten, it's just not happening.",
        "The halibut came with this lemon butter sauce, it was amazing.",
        "Let's go back to the first design, the second one felt too busy.",
        "Who has the mentor sign-up sheet? I want to book someone for later.",
        "Okay, everyone, five more minutes and then we line up for judging.",
    ],
]


def pcm_of(b: bytes) -> array.array:
    return array.array("h", b[: len(b) // 2 * 2])


def clamp(x: float) -> int:
    return max(-32768, min(32767, int(x)))


def rms_dbfs(samples: array.array) -> float:
    rms = math.sqrt(sum(x * x for x in samples) / max(len(samples), 1))
    return 20 * math.log10(rms / 32768) if rms else -120.0


def active_dbfs(pcm: bytes) -> float:
    """RMS over the 100 ms frames within 30 dB of the loudest one (speech, not pauses)."""
    frames = [pcm[i : i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES)]
    top = max(frame_dbfs(f) for f in frames)
    voiced = b"".join(f for f in frames if frame_dbfs(f) > top - 30)
    return rms_dbfs(pcm_of(voiced))


def scaled(pcm: bytes, gain_db: float) -> array.array:
    g = 10 ** (gain_db / 20)
    return array.array("h", (clamp(x * g) for x in pcm_of(pcm)))


def far(samples: array.array, cutoff_hz: float = 2500.0) -> array.array:
    """A talker a few metres away: one-pole low-pass plus early reflections."""
    a = math.exp(-2 * math.pi * cutoff_hz / SR)
    lp, y = [0.0] * len(samples), 0.0
    for i, x in enumerate(samples):
        y = (1 - a) * x + a * y
        lp[i] = y
    taps = [(int(ms * SR / 1000), g) for ms, g in ((17, 0.5), (29, 0.4), (43, 0.33),
            (61, 0.27), (89, 0.2), (127, 0.15))]  # fmt: skip
    out = lp[:]
    for d, g in taps:
        for i in range(d, len(lp)):
            out[i] += g * lp[i - d]
    return array.array("h", (clamp(x) for x in out))


def cached(name: str, make: Callable[[], bytes]) -> bytes:
    path = FIX / name
    if not path.exists():
        FIX.mkdir(exist_ok=True)
        path.write_bytes(make())
        log(f"wrote {path.name} ({path.stat().st_size / 32000:.1f} s)")
    return path.read_bytes()


def make_babble(http: httpx.Client, secs: float = 80.0) -> bytes:
    n = int(secs * SR)
    mixed = [0.0] * n
    gap = bytes(int(0.4 * SR) * 2)
    for k, (voice, lines) in enumerate(zip(BABBLE_VOICES, BABBLE, strict=True)):
        track = pcm_of(gap.join(tts(http, voice, t) for t in lines) + gap)
        off = k * int(2.3 * SR)
        for i in range(n):
            mixed[i] += track[(i + off) % len(track)]
    return far(array.array("h", (clamp(x / 2) for x in mixed))).tobytes()


@dataclass
class Fixtures:
    cmds: list[bytes]
    babble: bytes
    conv: bytes
    near: bytes


def load_fixtures() -> Fixtures:
    with httpx.Client(base_url=API, headers={"xi-api-key": api_key()}, timeout=60) as http:
        cmds = [
            cached(f"cmd_{w}.pcm", lambda p=p: tts(http, SERVER_VOICE, p)) for w, p, _ in PHRASES
        ]
        babble = cached("babble4_far.pcm", lambda: make_babble(http))
        gap = bytes(int(0.8 * SR) * 2)
        near = cached(
            "near_misses.pcm",
            lambda: gap.join(tts(http, SERVER_VOICE, t) for t in NEAR_MISSES) + gap,
        )
    conv = (FIX / "conv_task.pcm").read_bytes()
    norm = [scaled(c, CMD_DBFS - active_dbfs(c)).tobytes() for c in cmds]
    return Fixtures(
        cmds=norm,
        babble=babble,
        conv=scaled(conv, CMD_DBFS - active_dbfs(conv)).tobytes(),
        near=scaled(near, CMD_DBFS - active_dbfs(near)).tobytes(),
    )


def bed(babble: bytes, level_db: float | None, secs: float, seed: int) -> list[float]:
    n = int(secs * SR)
    if level_db is None:
        return [0.0] * n
    b = pcm_of(babble)
    g = 10 ** ((CMD_DBFS + level_db - rms_dbfs(b)) / 20)
    off = random.Random(seed).randrange(len(b))
    return [g * b[(i + off) % len(b)] for i in range(n)]


def command_run(fx: Fixtures, level_db: float | None, seed: int):
    """Babble bed with every command on it; returns the PCM and (match, start, end) per
    command in audio seconds."""
    total = LEAD + SPACING * len(fx.cmds) + 2.0
    mix = bed(fx.babble, level_db, total, seed)
    expected = []
    for k, (cmd, (word, _, match)) in enumerate(zip(fx.cmds, PHRASES, strict=True)):
        t0 = LEAD + SPACING * k
        start = int(t0 * SR)
        for i, x in enumerate(pcm_of(cmd)):
            mix[start + i] += x
        end = t0 + max(speech_end_offset(cmd), 0.1)
        expected.append((word, match, t0, end))
    return array.array("h", (clamp(x) for x in mix)).tobytes(), expected


def speech_end_offset(pcm: bytes) -> float:
    frames = [frame_dbfs(pcm[i : i + FRAME_BYTES]) for i in range(0, len(pcm), FRAME_BYTES)]
    last = max((i for i, d in enumerate(frames) if d > CMD_DBFS - 25), default=0)
    return (last + 1) * FRAME_SECS


@dataclass
class Config:
    keyterms: bool
    vad: float | None
    gate: float | None
    hold: int
    fbg: bool


async def stream(pcm: bytes, cfg: Config, sem: asyncio.Semaphore):
    async with sem:
        commits: list[tuple[float, str]] = []
        stt = ScribeStream(
            lambda text: None,
            lambda text, t: commits.append((t, text)),
            vad_threshold=cfg.vad,
            keyterms=keyterms() if cfg.keyterms else (),
            filter_background=cfg.fbg,
        )
        await stt.open()
        gate = LoudnessGate(cfg.gate, cfg.hold)
        frames = [pcm[i : i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES)]
        start = time.monotonic()
        for n, frame in enumerate(frames):
            await asyncio.sleep(max(0.0, start + n * FRAME_SECS - time.monotonic()))
            await stt.send(gate(frame))
        await stt.finish()
        return [(t - start, text) for t, text in commits]


def parsed(commits, soundalikes: bool) -> list[tuple[float, Command]]:
    return [(t, c) for t, text in commits for c in parse_commands(text, soundalikes=soundalikes)]


def score(commits, expected, soundalikes: bool):
    got = parsed(commits, soundalikes)
    used: set[int] = set()
    hits, lat, missed = 0, [], []
    for word, match, t0, end in expected:
        k = next(
            (i for i, (t, c) in enumerate(got)
             if i not in used and t0 <= t <= end + WINDOW and match(c)),
            None,
        )  # fmt: skip
        if k is None:
            missed.append(word)
            continue
        used.add(k)
        hits += 1
        lat.append(got[k][0] - end)
    extra = [c for i, (_, c) in enumerate(got) if i not in used]
    wrong = [c.intent for c in extra if c.intent != "unknown"]
    unknown = [c.words for c in extra if c.intent == "unknown"]
    return hits, lat, missed, wrong, unknown


def false_triggers(commits, soundalikes: bool):
    got = [c for _, c in parsed(commits, soundalikes)]
    return [c.intent for c in got if c.intent != "unknown"], [
        c.words for c in got if c.intent == "unknown"
    ]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyterms", action="store_true")
    ap.add_argument("--vad", type=float, help="Scribe vad_threshold (default 0.4)")
    ap.add_argument("--gate", type=float, help="LoudnessGate dBFS (default off)")
    ap.add_argument("--hold", type=int, default=3)
    ap.add_argument("--fbg", action="store_true", help="filter_background_audio")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--dump", type=Path, help="write every committed transcript here (JSON)")
    args = ap.parse_args()
    cfg = Config(args.keyterms, args.vad, args.gate, args.hold, args.fbg)
    fx = load_fixtures()
    sem = asyncio.Semaphore(args.concurrency)
    levels: list[float | None] = [None, *LEVELS]
    runs = [(lv, r, *command_run(fx, lv, seed=r)) for lv in levels for r in range(args.repeat)]
    ft_runs = [("conversation 59 s", fx.conv), ("near misses", fx.near)] + [
        (f"babble {lv:+.0f} dB", array.array("h", (clamp(x) for x in bed(
            fx.babble, lv, 60.0, seed=99))).tobytes())
        for lv in LEVELS
    ]  # fmt: skip
    log(f"config {cfg}; {len(runs)} command runs, {len(ft_runs)} false-trigger runs")
    results = await asyncio.gather(
        *(stream(pcm, cfg, sem) for _, _, pcm, _ in runs),
        *(stream(pcm, cfg, sem) for _, pcm in ft_runs),
    )
    if args.dump:
        names = [f"cmd {lv} r{r}" for lv, r, _, _ in runs] + [n for n, _ in ft_runs]
        args.dump.write_text(json.dumps(dict(zip(names, results, strict=True))))
    summary: dict[str, object] = {"config": cfg.__dict__}
    for sa in (False, True):
        tag = "soundalikes" if sa else "exact"
        table: dict[str, object] = {}
        for lv in levels:
            name = "clean" if lv is None else f"{lv:+.0f} dB"
            hits = n = 0
            lats: list[float] = []
            wrong: list[str] = []
            unknown: list[str] = []
            for (rl, r, _, expected), commits in zip(runs, results, strict=False):
                if rl != lv:
                    continue
                h, lat, missed, w, u = score(commits, expected, sa)
                hits, n = hits + h, n + len(expected)
                lats += lat
                wrong += w
                unknown += u
                if args.verbose and sa and (missed or w):
                    print(f"  [{name} r{r}] missed {missed} wrong {w}")
                    for t, text in commits:
                        print(f"      {t:6.1f} {text}")
            table[name] = {
                "hit": f"{hits}/{n}",
                "wrong": wrong,
                "unknown": len(unknown),
                "lat_med": round(statistics.median(lats), 2) if lats else None,
            }
            print(f"[{tag}] {name:>8}: {hits}/{n} recognised, wrong {wrong}, "
                  f"unknown {len(unknown)}, latency median "
                  f"{statistics.median(lats) if lats else float('nan'):.2f} s")  # fmt: skip
        ft: dict[str, object] = {}
        for (name, _), commits in zip(ft_runs, results[len(runs) :], strict=True):
            found, unk = false_triggers(commits, sa)
            ft[name] = {"false": found, "unknown": unk}
            print(f"[{tag}] false triggers in {name}: {found} (unknown {unk})")
            if args.verbose and sa and found:
                for t, text in commits:
                    print(f"      {t:6.1f} {text}")
        summary[tag] = {"recognition": table, "false_triggers": ft}
    print("SUMMARY " + json.dumps(summary))


if __name__ == "__main__":
    asyncio.run(main())
