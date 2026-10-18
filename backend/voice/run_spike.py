"""Voice spike CLI: PCM files -> Scribe realtime -> text-only agent -> order tools.

Usage:
  python run_spike.py fixtures/01_order.pcm [more.pcm ...] [--repeat 5]
  python run_spike.py --text "Table twelve. Seat one, the halibut." [...]   (skip the mic/STT)
All files run in one agent session, in order. Prints partial and committed transcripts,
every tool call, per-utterance latency and the final order by seat as JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from order import Menu, OrderBook
from voice_session import AgentSession, log, stream_to_scribe


def agent_id() -> str:
    env = os.environ.get("ELEVENLABS_AGENT_ID")
    saved = Path(__file__).with_name(".agent_id")
    if env:
        return env
    if saved.exists():
        return saved.read_text().strip()
    raise SystemExit("[fs] no agent: run create_agent.py or set ELEVENLABS_AGENT_ID")


async def run_once(inputs: list[str], text_mode: bool) -> tuple[dict[str, Any], list[float]]:
    book = OrderBook(Menu.load())
    tool_times: list[float] = []

    def on_tool(name: str, params: dict, result: dict, is_error: bool, t: float) -> None:
        tool_times.append(t)
        tag = "ERROR" if is_error else "ok"
        log(f"tool {name}({json.dumps(params)}) -> {tag} {json.dumps(result)}")

    session = AgentSession(agent_id(), book, on_tool, lambda text: log(f"agent: {text}"))
    await session.start()
    segments: asyncio.Queue[str | None] = asyncio.Queue()

    async def forward() -> None:
        while True:
            text = await segments.get()
            try:
                if text is None:
                    return
                await session.say(text)
            finally:
                segments.task_done()

    worker = asyncio.create_task(forward())
    latencies: list[float] = []
    try:
        for item in inputs:
            log(f"=== {item if text_mode else Path(item).name}")
            first_tool = len(tool_times)
            if text_mode:
                speech_end = time.monotonic()
                log(f"committed: {item}")
                segments.put_nowait(item)
            else:

                def on_committed(text: str, t: float) -> None:
                    log(f"committed: {text}")
                    segments.put_nowait(text)

                speech_end = await stream_to_scribe(
                    Path(item).read_bytes(), lambda text: log(f"partial: {text}"), on_committed
                )
            await segments.join()
            calls = [t for t in tool_times[first_tool:] if t >= speech_end]
            if calls:
                latencies.append(calls[0] - speech_end)
                log(f"latency end of speech -> first tool call: {calls[0] - speech_end:.2f} s")
            else:
                log("no tool call after end of speech for this input")
    finally:
        segments.put_nowait(None)
        await worker
        await session.close()
    return book.snapshot(), latencies


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", help="PCM files (16 kHz s16le mono) or --text lines")
    ap.add_argument("--text", action="store_true", help="inputs are transcript text, skip STT")
    ap.add_argument("--repeat", type=int, default=1, help="fresh sessions, for latency medians")
    args = ap.parse_args()
    all_latencies: list[float] = []
    for run in range(1, args.repeat + 1):
        if args.repeat > 1:
            log(f"##### run {run}/{args.repeat}")
        order, latencies = asyncio.run(run_once(args.inputs, args.text))
        all_latencies += latencies
        print(json.dumps(order, indent=2))
    if all_latencies:
        log(
            f"latency over {len(all_latencies)} utterances: median "
            f"{statistics.median(all_latencies):.2f} s, min {min(all_latencies):.2f} s, "
            f"max {max(all_latencies):.2f} s"
        )


if __name__ == "__main__":
    main()
