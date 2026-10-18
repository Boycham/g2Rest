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


def test_order_task_table_live_draft_and_fire_close_the_task() -> None:
    async def run() -> None:
        starts: list[dict[str, Any]] = []

        async def relay(ws: ServerConnection) -> None:
            async for data in ws:
                if isinstance(data, bytes):
                    continue
                msg = json.loads(data)
                if msg["type"] == "capture.start":
                    starts.append(msg)
                    await ws.send(json.dumps(draft(table=msg.get("table"))))
                elif msg["type"] == "order.confirm" and "proposalId" not in msg:
                    await ws.send(json.dumps(draft("sent", table=msg.get("table") or "T3")))

        async with serve(relay, "localhost", 0) as server:
            port = server.sockets[0].getsockname()[1]
            hub = Hub(Store.from_settings(Settings()), f"ws://localhost:{port}/ws")
            glasses, org = FakeWs(), FakeWs()
            await hub.join(glasses, "server", "s1")  # type: ignore[arg-type]
            await hub.join(org, "organizer", "organizer")  # type: ignore[arg-type]
            task, out = hub.store.book.create("ORDER", "T3", hub.store.now())
            await hub.deliver(out)
            await hub.on_text(glasses, json.dumps({"type": "task.accept", "taskId": task.id}))  # type: ignore[arg-type]

            start = {"type": "capture.start", "captureId": "cap-1", "mode": "clip"}
            await hub.on_text(glasses, json.dumps(start))  # type: ignore[arg-type]
            await until(lambda: any(m.get("type") == "order.draft" for m in org.sent))
            assert starts[0]["table"] == "T3" and starts[0]["mode"] == "clip"
            live = next(m for m in org.sent if m.get("type") == "order.draft")
            assert live["orderId"] == "order-r1" and live["status"] == "draft"
            assert live["table"] == "T3" and live["lines"][0]["dish"] == "Pan-Roasted Halibut"

            await hub.on_text(glasses, '{"type": "order.confirm", "orderId": "r1"}')  # type: ignore[arg-type]
            await until(lambda: hub.store.book.get(task.id).state == "done")
            assert any(
                m.get("type") == "task.updated" and m["task"]["state"] == "done"
                for m in glasses.sent
            )
            hub.leave(glasses)  # type: ignore[arg-type]

    asyncio.run(run())


def test_tableless_live_draft_is_labelled_and_capture_has_no_table() -> None:
    async def run() -> None:
        async def relay(ws: ServerConnection) -> None:
            async for data in ws:
                if isinstance(data, str) and json.loads(data)["type"] == "capture.start":
                    await ws.send(json.dumps(draft(table=None)))

        async with serve(relay, "localhost", 0) as server:
            port = server.sockets[0].getsockname()[1]
            hub = Hub(Store.from_settings(Settings()), f"ws://localhost:{port}/ws")
            glasses, org = FakeWs(), FakeWs()
            await hub.join(glasses, "server", "s1")  # type: ignore[arg-type]
            await hub.join(org, "organizer", "organizer")  # type: ignore[arg-type]
            _, out = hub.store.book.create("RUN", "T1", hub.store.now())  # not an ORDER task
            await hub.deliver(out)
            await hub.on_text(glasses, '{"type": "capture.start", "captureId": "c2"}')  # type: ignore[arg-type]
            await until(lambda: any(m.get("type") == "order.draft" for m in org.sent))
            assert hub.store.captures["c2"].table is None
            live = next(m for m in org.sent if m.get("type") == "order.draft")
            assert live["table"] == "TABLE?"
            hub.leave(glasses)  # type: ignore[arg-type]

    asyncio.run(run())


def test_command_stream_survives_a_clip_and_voice_commands_reach_the_glasses() -> None:
    async def run() -> None:
        frames: list[bytes] = []
        starts: list[dict[str, Any]] = []

        async def relay(ws: ServerConnection) -> None:
            async for data in ws:
                if isinstance(data, bytes):
                    frames.append(data)
                    await ws.send(json.dumps({"type": "voice.command", "intent": "accept"}))
                    continue
                msg = json.loads(data)
                if msg["type"] == "capture.start":
                    starts.append(msg)

        async with serve(relay, "localhost", 0) as server:
            port = server.sockets[0].getsockname()[1]
            hub = Hub(Store.from_settings(Settings()), f"ws://localhost:{port}/ws")
            glasses = FakeWs()
            await hub.join(glasses, "server", "s1")  # type: ignore[arg-type]
            cmd = '{"type": "capture.start", "captureId": "cmd-1", "mode": "command"}'
            await hub.on_text(glasses, cmd)  # type: ignore[arg-type]
            clip = '{"type": "capture.start", "captureId": "clip-1", "mode": "clip"}'
            await hub.on_text(glasses, clip)  # type: ignore[arg-type]
            await hub.on_bytes(glasses, b"\1" * 3200)  # type: ignore[arg-type]
            await hub.on_text(glasses, '{"type": "capture.stop", "captureId": "clip-1"}')  # type: ignore[arg-type]
            await hub.on_bytes(glasses, b"\2" * 3200)  # type: ignore[arg-type]
            await until(lambda: len(frames) == 2)
            assert frames == [b"\1" * 3200, b"\2" * 3200]  # the command stream after the clip
            assert hub.store.captures["cmd-1"].table is None
            assert "table" not in starts[0] and starts[0]["mode"] == "command"
            await until(lambda: any(m["type"] == "voice.command" for m in glasses.sent))
            assert {"type": "voice.command", "intent": "accept"} in glasses.sent
            hub.leave(glasses)  # type: ignore[arg-type]

    asyncio.run(run())


def test_voice_accept_frame_from_another_server_is_rejected() -> None:
    async def run() -> None:
        hub = Hub(Store.from_settings(Settings()))
        mine, other = FakeWs(), FakeWs()
        await hub.join(mine, "server", "s1")  # type: ignore[arg-type]
        await hub.join(other, "server", "s2")  # type: ignore[arg-type]
        task, out = hub.store.book.create("RUN", "T2", now=0, assignee="s1")
        await hub.deliver(out)
        task_id = task.id
        await hub.on_text(other, f'{{"type": "task.accept", "taskId": "{task_id}"}}')  # type: ignore[arg-type]
        assert hub.store.book.get(task_id).state != "accepted"
        await hub.on_text(mine, f'{{"type": "task.accept", "taskId": "{task_id}"}}')  # type: ignore[arg-type]
        assert hub.store.book.get(task_id).state == "accepted"

    asyncio.run(run())
