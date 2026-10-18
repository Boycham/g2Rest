"""Create the text-only order agent and its client tools via the ElevenLabs API.

Usage: python create_agent.py [--llm gemini-2.5-flash] [--dry-run]
Writes the new agent id to .agent_id (gitignored) and prints it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from order import Menu
from voice_session import API, HTTP_TIMEOUT, TOOL_SCHEMAS, api_key, log

AGENT_NAME = "floor-sense-order-spike"
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


def build_payloads(llm: str) -> tuple[list[dict], dict]:
    tools = [
        {
            "tool_config": {
                "type": "client",
                **schema,
                "expects_response": True,
                "response_timeout_secs": TOOL_TIMEOUT_SECS,
            }
        }
        for schema in TOOL_SCHEMAS
    ]
    agent = {
        "name": AGENT_NAME,
        "tags": ["floor-sense", "spike"],
        "conversation_config": {
            "conversation": {"text_only": True},
            "agent": {
                "first_message": "",
                "language": "en",
                "prompt": {
                    "prompt": PROMPT.format(menu=Menu.load().prompt_text()),
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
    ap.add_argument("--llm", default="gemini-2.5-flash")
    ap.add_argument("--dry-run", action="store_true", help="print payloads, call nothing")
    args = ap.parse_args()
    tools, agent = build_payloads(args.llm)
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
