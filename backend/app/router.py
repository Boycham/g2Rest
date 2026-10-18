"""Gemini picks who gets a new task; the rules decide whenever Gemini can't.

One generateContent call per task, constrained to an enum of the server ids. No key, an error,
a timeout or an answer outside the servers all fall back to the rule pick (the table's section
server, `Floor.escalation_chain`), so routing never stalls on the model.
Escalation, bounces and RUN tasks from the pass planner stay on the rules.
Every pick is logged as `router.pick`, which doubles as training data for a later model.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.state import Store

log = logging.getLogger("fs")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
INSTRUCTIONS = (
    "You route tasks to servers in a restaurant. Pick the one server who should do this task. "
    "Prefer a server who covers the table's section. Avoid servers carrying food (an open RUN) "
    "or with more open tasks than the others. Keep tasks with allergies or notes with the "
    "section's server unless they are swamped. Answer with the server id only."
)


def context(store: Store, kind: str, table: str, notes: list[str]) -> dict[str, Any]:
    """What Gemini sees: the task, its table and every server's current load."""
    section = store.floor.table(table).section
    servers = [
        {
            "id": s.id,
            "name": s.name,
            "coversTable": s.id in store.floor.servers_for_section(section),
            "openTasks": [
                {"kind": t.kind, "table": t.table, "state": t.state}
                for t in store.book.open_for(s.id)
            ],
        }
        for s in store.floor.servers.values()
    ]
    return {
        "task": {"kind": kind, "table": table, "section": section, "notes": notes},
        "tableStatus": store.tables[table].status,
        "servers": servers,
    }


async def pick(
    store: Store, client: httpx.AsyncClient, kind: str, table: str, notes: list[str]
) -> str:
    rule = store.floor.escalation_chain(table)[0]
    settings = store.settings
    if not settings.gemini_api_key:
        return rule
    ctx = context(store, kind, table, notes)
    ids = [s["id"] for s in ctx["servers"]]
    body = {
        "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(ctx)}]}],
        "generationConfig": {
            "responseMimeType": "text/x.enum",
            "responseSchema": {"type": "STRING", "enum": ids},
        },
    }
    started = time.monotonic()
    how, who = "rules", rule
    try:
        r = await client.post(
            URL.format(model=settings.gemini_model),
            json=body,
            headers={"x-goog-api-key": settings.gemini_api_key},
            timeout=settings.router_timeout_sec,
        )
        r.raise_for_status()
        answer = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        if answer in ids:
            how, who = "gemini", answer
        else:
            log.warning("[fs] router: Gemini answered %r, not a server; using rules", answer)
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
        log.warning("[fs] router: Gemini failed (%s); using rules", type(e).__name__)
    ms = round((time.monotonic() - started) * 1000)
    store.events.append(
        "router.pick", kind=kind, table=table, assignee=who, rule=rule, how=how, ms=ms
    )
    return who
