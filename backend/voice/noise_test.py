"""Voice-command noise test (dev only; audio stays in memory, nothing is written).

python noise_test.py   -> Scribe batch on "verity <command>" in noise + conversation, and on
conversation with no commands. Prints spellings, recognition and false triggers.
"""

from __future__ import annotations

import array
import asyncio
import random
from pathlib import Path

import httpx

from commands import COMMANDS, find_commands
from make_fixtures import GUEST_VOICE, SERVER_VOICE, add_noise, tts
from voice_session import API, api_key, transcribe_clip

FIX = Path(__file__).with_name("fixtures")
NEAR_MISSES = [
    "That was very tasty, thank you.",
    "Could you verify the bill for us?",
    "Verity is my sister's name, actually.",
    "We're done, I accept, let's go back up to the room.",
]


def mix(fg: bytes, bg: bytes, bg_gain: float) -> bytes:
    a, b = array.array("h", fg), array.array("h", bg)
    off = random.Random(len(fg)).randrange(0, max(1, len(b) - len(a)))
    return array.array(
        "h", (max(-32768, min(32767, int(x + bg_gain * b[off + i]))) for i, x in enumerate(a))
    ).tobytes()


def text_of(turns: list[tuple[str, str]]) -> str:
    return " ".join(t for _, t in turns)


async def main() -> None:
    conv = (FIX / "conv_task.pcm").read_bytes()
    pad = bytes(16000)  # 0.5 s
    with httpx.Client(base_url=API, headers={"xi-api-key": api_key()}, timeout=30) as http:
        cmds = {(w, v): tts(http, v, f"Verity, {w}.") for w in COMMANDS for v in (SERVER_VOICE,)}
        near = tts(http, GUEST_VOICE, " ".join(NEAR_MISSES))
    hits = total = 0
    spell: dict[str, int] = {}
    conditions = (
        ("clean", 0.0, None),
        ("babble -12 dB", 0.25, None),
        ("babble -12 dB + white 10 dB", 0.25, 10),
        ("babble -6 dB", 0.5, None),
    )
    for cond, gain, snr in conditions:
        ok = 0
        for (w, _), pcm in cmds.items():
            clip = pad + pcm + pad
            if gain:
                clip = mix(clip, conv, gain)
            if snr is not None:
                clip = add_noise(clip, snr)
            heard = text_of(await transcribe_clip(clip, diarize=False))
            first = (heard.lower().split() or [""])[0].strip(",.")
            spell[first] = spell.get(first, 0) + 1
            got = find_commands(heard)
            ok += got == [w]
            print(f"[{cond}] {w!r}: heard {heard!r} -> {got}")
        hits += ok
        total += len(cmds)
        print(f"== {cond}: {ok}/{len(cmds)} recognised")
    print(f"== overall {hits}/{total}; first-word spellings {spell}")
    false = 0
    for name, pcm in (
        ("conv_task", conv),
        ("conv_task+noise", add_noise(conv, 5)),
        ("near misses", near),
    ):
        heard = text_of(await transcribe_clip(pcm, diarize=False))
        found = find_commands(heard)
        false += len(found)
        print(f"== false triggers in {name} ({len(pcm) / 32000:.0f} s): {found}")
    print(f"== false triggers total {false}")


if __name__ == "__main__":
    asyncio.run(main())
