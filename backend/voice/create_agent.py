"""Create the text-only order agent and its client tools via the ElevenLabs API.

Usage: python create_agent.py [--mode clip|stream] [--llm gemini-2.5-flash] [--dry-run]
`clip` (default): the conversational-capture agent, one set_order call per minute-long clip.
`stream`: the earlier per-segment agent used by run_spike.py.
Writes the new agent id to .agent_id (gitignored) and prints it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from order import Menu
from voice_session import API, CLIP_TOOL_SCHEMAS, HTTP_TIMEOUT, TOOL_SCHEMAS, api_key, log

AGENT_NAME = "floor-sense-order-spike"
CLIP_AGENT_NAME = "floor-sense-clip-order"
TOOL_TIMEOUT_SECS = 10

PROMPT = """You turn a restaurant server's spoken order into tool calls. Each user message is
one transcript segment from speech-to-text, so words may be misheard and numbers may be
spelled out ("seat two" means seat 2).

Menu (use these exact names in tool calls):
{menu}

Rules:
- Remember the current table from earlier messages; every tool call needs it.
- Call add_item once per dish per seat. Put requested changes such as "no butter" in
  alterations; never drop them.
- "Actually, no X for seat N" or "scratch the X" means remove_item. remove_item only
  proposes; the server taps to apply it. If it returns an error (the dish is not on that
  seat), do not remove a different dish instead.
- Allergies go to set_allergy for that seat.
- You CANNOT send or cancel orders. confirm_order and cancel_order only propose; the server
  taps on the glasses to do it. Never say an order was sent or cancelled. For "cancel the
  dessert" call cancel_order with items ["dessert"].
- If a tool returns an error, fix the arguments using its suggestions and retry once;
  otherwise say in a few words what is wrong.
- Replies are shown on smart glasses: at most 8 words, no greetings, no questions unless the
  table or seat is genuinely unknown."""


CLIP_PROMPT = """You read the transcript of the last minute at one restaurant table, picked up
by the server's smart glasses: the server, the guests, and sometimes people at nearby tables.
Speaker labels come from voice diarization and may be wrong. Speech-to-text may mishear words.

Menu (use these exact names):
{menu}

For every clip, call set_order exactly once with the complete order for this table.
- Only ordering intent counts: dishes a guest orders, drops or changes, alterations
  ("no butter"), and allergies. Ignore small talk, the server's own suggestions unless a guest
  takes them, and anything said by or about other tables.
- guest: number the guests 1, 2, 3 in the order they first order or state an allergy. Use seat
  only when a seat number is said aloud. Guests may share one speaker label, so a new guest
  starts whenever the words say so: "and I'd like", "for me", "I'll have" after someone else
  ordered, or the server turning to another person ("and for you?"). One guest's own
  follow-up ("oh, and I have an allergy") stays with that guest.
- If a choice is ambiguous ("the fish" when two dishes fit) or not on the menu, do not guess:
  put it in unclear as a short statement, e.g. "'the fish': halibut or salmon".
- notes: occasion, pacing or timing the server or kitchen should know (a few words each).
- table: only if a table number is said for this order ("that was table two").
- If this clip continues an order you already returned in this conversation, return the
  complete order again and pass the seat numbers from your last result.
- You cannot send or cancel orders; the server taps on the glasses. Nobody can answer you:
  the glasses have no speaker and your text is never shown. Never ask questions. After the
  tool call, reply with "ok" only."""


def build_payloads(llm: str, mode: str = "clip") -> tuple[list[dict], dict]:
    tools = [
        {
            "tool_config": {
                "type": "client",
                **schema,
                "expects_response": True,
                "response_timeout_secs": TOOL_TIMEOUT_SECS,
            }
        }
        for schema in (CLIP_TOOL_SCHEMAS if mode == "clip" else TOOL_SCHEMAS)
    ]
    prompt = CLIP_PROMPT if mode == "clip" else PROMPT
    agent = {
        "name": CLIP_AGENT_NAME if mode == "clip" else AGENT_NAME,
        "tags": ["floor-sense", "spike"],
        "conversation_config": {
            "conversation": {"text_only": True},
            "agent": {
                "first_message": "",
                "language": "en",
                "prompt": {
                    "prompt": prompt.format(menu=Menu.load().prompt_text()),
                    "llm": llm,
                    "temperature": 0,
                    "tool_ids": [],
                },
            },
        },
    }
    return tools, agent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("clip", "stream"), default="clip")
    # Measured on conv_task (NOTES.md): claude-haiku-4-5 was right 4/5 at ~4.0 s; gemini-2.5-flash
    # 3/5 at ~6.5 s; gpt-4.1-mini 3/5 at ~2.5 s with a 20 s stall; gemini-2.5-flash-lite 0/5.
    ap.add_argument("--llm", default="claude-haiku-4-5")
    ap.add_argument("--dry-run", action="store_true", help="print payloads, call nothing")
    args = ap.parse_args()
    tools, agent = build_payloads(args.llm, args.mode)
    if args.dry_run:
        print(json.dumps({"tools": tools, "agent": agent}, indent=2))
        return
    headers = {"xi-api-key": api_key()}
    with httpx.Client(base_url=API, headers=headers, timeout=HTTP_TIMEOUT) as http:
        for tool in tools:
            r = http.post("/v1/convai/tools", json=tool)
            if r.is_error:
                raise SystemExit(f"[fs] tool create failed {r.status_code}: {r.text}")
            tool_id = r.json()["id"]
            agent["conversation_config"]["agent"]["prompt"]["tool_ids"].append(tool_id)
            log(f"tool {tool['tool_config']['name']} -> {tool_id}")
        r = http.post("/v1/convai/agents/create", json=agent)
        if r.is_error:
            raise SystemExit(f"[fs] agent create failed {r.status_code}: {r.text}")
    agent_id = r.json()["agent_id"]
    Path(__file__).with_name(".agent_id").write_text(agent_id + "\n")
    log(f"agent {agent_id} (saved to .agent_id; or set ELEVENLABS_AGENT_ID)")


if __name__ == "__main__":
    main()
