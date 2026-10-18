"""Generate the spike's test utterances with ElevenLabs TTS as raw 16 kHz s16le mono PCM.

Usage: python make_fixtures.py [--snr-db 5]
Writes fixtures/*.pcm (gitignored; never commit audio). --snr-db also writes noisy copies.
The conv_* fixtures are minute-long table conversations in two voices (the server and the
guests) for the clip path: small talk, one off-topic bystander line, and an ambiguous dish.
"""

from __future__ import annotations

import argparse
import array
import math
import os
import random
from pathlib import Path

import httpx

from voice_session import API, api_key, log

FIXTURES = Path(__file__).with_name("fixtures")
DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"  # premade voice used in the TTS API reference example
SERVER_VOICE = DEFAULT_VOICE  # George (premade)
GUEST_VOICE = "EXAVITQu4vr4xnSDxMaL"  # Sarah (premade), all guests and the bystander
GAP_SECS = 0.7
S, G = "server", "guest"
# No table or seat words in conv_task: the ORDER task gives the table, code numbers the seats.
CONVERSATIONS = {
    "conv_task": [
        (S, "Good evening, everyone, welcome in. How are we doing tonight?"),
        (G, "Oh, we're doing well. It took us forever to find parking, though."),
        (S, "I'm sorry about that, it gets busy around here on Saturdays."),
        (G, "No worries. This place is beautiful. Are those lights new?"),
        (S, "They are! We just put them up last month. We're glad you like them."),
        (G, "We do. And honestly, we're starving, it's been a long day."),
        (G, "We're great, thank you. It's our anniversary, actually."),
        (S, "Oh, congratulations! Have you had a chance to look at the menu?"),
        (G, "We have. I'll have the halibut, but no butter, please."),
        (G, "And I'd like the salmon with no dill. Oh, and I have a shellfish allergy."),
        (G, "Did anyone catch the game last night? What a finish."),
        (S, "Of course. And for you, sir?"),
        (G, "Hmm. I think I'll just get the fish."),
        (G, "And we're in no rush tonight, so take your time with the mains."),
        (S, "Perfect. I'll get that started for you right away."),
    ],
    "conv_tableless": [
        (S, "Hi there, welcome. Can I start you off with anything?"),
        (G, "Thanks. The weather has been so nice this week, hasn't it?"),
        (S, "It really has. Do you know what you'd like?"),
        (G, "Yes, I'll have the ribeye, medium rare, with the sauce on the side."),
        (G, "And the mushroom risotto for me, no truffle oil."),
        (S, "Great choices. Anything to start?"),
        (G, "The burrata to share, please. That's everything."),
        (S, "Lovely, I'll be right back with some bread."),
        (S, "Okay, that was table two."),
    ],
}
# The same order before the server names the table: the draft shows TABLE? until a second
# swipe down sends conv_tableless, whose last line is "that was table two".
CONVERSATIONS["conv_notable"] = CONVERSATIONS["conv_tableless"][:-1]
TTS_MODEL = "eleven_multilingual_v2"
UTTERANCES = {
    # Soup and torte are ordered so fixtures 2 and 4 remove something that is there; after
    # both removals are tapped the order matches the voice test's.
    "01_order": "Table two. Seat one, the halibut, no butter, and the chocolate torte. "
    "Seat two, the salmon, no dill, and the tomato soup.",
    "02_no_soup": "Actually, no soup for seat two.",
    "03_allergy": "Seat three has a shellfish allergy.",
    "04_cancel_dessert": "Cancel table two's dessert.",
}


def add_noise(pcm: bytes, snr_db: float, seed: int = 0) -> bytes:
    samples = array.array("h", pcm[: len(pcm) // 2 * 2])
    power = sum(s * s for s in samples) / max(len(samples), 1)
    sigma = math.sqrt(power / (10 ** (snr_db / 10)))
    rng = random.Random(seed)
    noisy = array.array(
        "h", (max(-32768, min(32767, int(s + rng.gauss(0, sigma)))) for s in samples)
    )
    return noisy.tobytes()


def tts(http: httpx.Client, voice: str, text: str) -> bytes:
    r = http.post(
        f"/v1/text-to-speech/{voice}",
        params={"output_format": "pcm_16000"},
        json={"text": text, "model_id": TTS_MODEL},
    )
    if r.is_error:
        raise SystemExit(f"[fs] tts failed {r.status_code}: {r.text[:300]}")
    return r.content


def conversation(http: httpx.Client, lines: list[tuple[str, str]]) -> bytes:
    gap = bytes(int(GAP_SECS * 16000) * 2)
    voices = {S: SERVER_VOICE, G: GUEST_VOICE}
    return gap.join(tts(http, voices[who], text) for who, text in lines) + gap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snr-db", type=float, help="also write white-noise copies at this SNR")
    args = ap.parse_args()
    voice = os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE
    FIXTURES.mkdir(exist_ok=True)
    with httpx.Client(base_url=API, headers={"xi-api-key": api_key()}, timeout=30) as http:
        clips = {name: tts(http, voice, text) for name, text in UTTERANCES.items()}
        clips |= {name: conversation(http, lines) for name, lines in CONVERSATIONS.items()}
        for name, pcm in clips.items():
            path = FIXTURES / f"{name}.pcm"
            path.write_bytes(pcm)
            log(f"{path.name}: {len(pcm) / 32000:.1f} s")
            if args.snr_db is not None:
                noisy = FIXTURES / f"{name}_snr{args.snr_db:g}.pcm"
                noisy.write_bytes(add_noise(pcm, args.snr_db))
                log(f"{noisy.name}: white noise at {args.snr_db:g} dB SNR")


if __name__ == "__main__":
    main()
