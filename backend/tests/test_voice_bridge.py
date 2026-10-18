"""The hub <-> voice relay bridge, against a scripted relay on a real local WebSocket."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

from app.config import Settings
from app.hub import Hub
from app.state import Store


class FakeWs:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_text(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


def draft(status: str = "draft", **extra: Any) -> dict[str, Any]:
    return {
        "type": "order.draft",
        "orderId": "r1",
        "captureId": "cap-1",
        "table": "T2",
        "lines": [
            {"seat": 1, "qty": 1, "dish": "halibut", "alterations": ["no butter"], "flagged": []},
            {
                "seat": 2,
                "qty": 1,
                "dish": "salmon",
                "alterations": [],
                "flagged": ["ketchup"],
            },
        ],
        "allergies": [{"allergen": "SHELLFISH", "seats": [3]}],
        "status": status,
        "pending": [],
        "voice": "listening",
        "notice": None,
        **extra,
    }


async def until(cond: Any, timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out")


def test_capture_audio_and_final_tap_fire_into_the_hub_store(tmp_path: Any) -> None:
    async def run() -> None:
        got: list[str | bytes] = []

        async def relay(ws: ServerConnection) -> None:
            async for data in ws:
                got.append(data)
                if isinstance(data, bytes):
                    continue
                msg = json.loads(data)
                if msg["type"] == "capture.start":
                    await ws.send(json.dumps(draft()))
                elif msg["type"] == "order.confirm" and "proposalId" not in msg:
                    await ws.send(json.dumps(draft("sent")))

        async with serve(relay, "localhost", 0) as server:
            port = server.sockets[0].getsockname()[1]
            hub = Hub(Store.from_settings(Settings()), f"ws://localhost:{port}/ws")
            glasses, org = FakeWs(), FakeWs()
            await hub.join(glasses, "server", "s1")  # type: ignore[arg-type]
            await hub.join(org, "organizer", "organizer")  # type: ignore[arg-type]
            await hub.on_text(glasses, '{"type": "capture.start", "captureId": "cap-1"}')  # type: ignore[arg-type]
            await hub.on_bytes(glasses, b"\0" * 3200)  # type: ignore[arg-type]
            await until(lambda: any(m["type"] == "order.draft" for m in glasses.sent))
            await until(lambda: any(isinstance(d, bytes) for d in got))
            assert hub.voice and hub.voice.owns(glasses, "r1")

            await hub.on_text(glasses, '{"type": "order.confirm", "orderId": "r1"}')  # type: ignore[arg-type]
            await until(lambda: any(m["type"] == "order.closed" for m in glasses.sent))
            assert glasses.sent[-1] == {"type": "order.closed", "orderId": "r1", "status": "fired"}

            order = hub.store.orders.get("order-r1")
            assert order is not None and order.status == "fired" and order.owner == "s1"
            assert [(ln.seat, ln.dish, ln.alterations, ln.flagged) for ln in order.lines] == [
                (1, "Pan-Roasted Halibut", ["no butter"], []),
                (2, "Cedar Plank Salmon", [], ["ketchup"]),
            ]
            assert order.allergies == {3: ["shellfish"]}
            assert any(m.get("type") == "order.fired" for m in org.sent)  # kitchen page
            hub.leave(glasses)  # type: ignore[arg-type]

    asyncio.run(run())


def test_unreachable_relay_shows_voice_offline() -> None:
    async def run() -> None:
        hub = Hub(Store.from_settings(Settings()), "ws://localhost:9/ws")
        glasses = FakeWs()
        await hub.join(glasses, "server", "s1")  # type: ignore[arg-type]
        await hub.on_text(glasses, '{"type": "capture.start", "captureId": "cap-9"}')  # type: ignore[arg-type]
        await until(lambda: any(m.get("voice") == "offline" for m in glasses.sent), 5)
        offline = glasses.sent[-1]
        assert offline["captureId"] == "cap-9" and offline["notice"] == "voice relay unreachable"

    asyncio.run(run())


def test_hub_orders_still_close_without_the_relay() -> None:
    async def run() -> None:
        hub = Hub(Store.from_settings(Settings()), "ws://localhost:9/ws")
        glasses = FakeWs()
        await hub.join(glasses, "server", "s1")  # type: ignore[arg-type]
        _, order = hub.store.orders.dispatch("add_item", {"table": "T2", "seat": 1, "dish": "soup"})
        assert order is not None and not hub.voice.owns(glasses, order.id)  # type: ignore[union-attr]
        await hub.on_text(glasses, json.dumps({"type": "order.confirm", "orderId": order.id}))  # type: ignore[arg-type]
        assert glasses.sent[-1] == {"type": "order.closed", "orderId": order.id, "status": "fired"}

    asyncio.run(run())
