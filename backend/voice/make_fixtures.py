"""Generate the spike's test utterances with ElevenLabs TTS as raw 16 kHz s16le mono PCM.

Usage: python make_fixtures.py [--snr-db 5]
Writes fixtures/*.pcm (gitignored; never commit audio). --snr-db also writes noisy copies.
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snr-db", type=float, help="also write white-noise copies at this SNR")
    args = ap.parse_args()
    voice = os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE
    FIXTURES.mkdir(exist_ok=True)
    with httpx.Client(base_url=API, headers={"xi-api-key": api_key()}, timeout=30) as http:
        for name, text in UTTERANCES.items():
            r = http.post(
                f"/v1/text-to-speech/{voice}",
                params={"output_format": "pcm_16000"},
                json={"text": text, "model_id": TTS_MODEL},
            )
            if r.is_error:
                raise SystemExit(f"[fs] tts failed {r.status_code}: {r.text[:300]}")
            path = FIXTURES / f"{name}.pcm"
            path.write_bytes(r.content)
            log(f"{path.name}: {len(r.content) / 32000:.1f} s")
            if args.snr_db is not None:
                noisy = FIXTURES / f"{name}_snr{args.snr_db:g}.pcm"
                noisy.write_bytes(add_noise(r.content, args.snr_db))
                log(f"{noisy.name}: white noise at {args.snr_db:g} dB SNR")


if __name__ == "__main__":
    main()
