from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import DATA_DIR, Settings
from app.eventdb import INSERT, EventDB, row, schema_statements
from app.events import EventLog
from app.main import create_app

TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}


class FakeConn:
    """Records what the writer sends; `fail` makes the next N writes raise like a dropped link."""

    def __init__(self, fail: int = 0) -> None:
        self.executed: list[str] = []
        self.batches: list[list[tuple[Any, ...]]] = []
        self.fail = fail
        self.closed = False

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append(query)
        return "OK"

    async def executemany(self, query: str, args: list[tuple[Any, ...]]) -> None:
        assert query == INSERT
        if self.fail:
            self.fail -= 1
            raise ConnectionResetError("connection lost")
        self.batches.append(list(args))

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        return [
            {
                "staff": "s1",
                "kind": "run",
                "n": 2,
                "avg_sec": 4.0,
                "p50_sec": 4.0,
                "p90_sec": 5.0,
                "max_sec": 5.0,
            }
        ]

    async def close(self) -> None:
        self.closed = True


def connector(*conns: FakeConn, down: int = 0):  # noqa: ANN201
    """Connects `down` times with an error (database unreachable), then hands out `conns`."""
    state = {"down": down, "next": list(conns)}

    async def connect() -> FakeConn:
        if state["down"]:
            state["down"] -= 1
            raise OSError("could not connect")
        return state["next"].pop(0)

    return connect


async def until(check, timeout: float = 3.0) -> None:  # noqa: ANN001
    end = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < end, "timed out"
        await asyncio.sleep(0.01)


def test_schema_file_has_the_hypertable_and_both_aggregates() -> None:
    sql = "\n".join(schema_statements())
    assert "create_hypertable('fs_events'" in sql
    assert "fs_accept_latency" in sql and "fs_ticket_time" in sql
    assert all("IF NOT EXISTS" in s or "if_not_exists" in s for s in schema_statements())


def test_row_fills_task_table_and_staff_where_present() -> None:
    log = EventLog()
    e = log.append("task.accepted", taskId="t7", table="T4", staff="s2", acceptSec=3.1)
    r = row(e, "boot1")
    assert r[1:7] == ("boot1", 1, "task.accepted", "t7", "T4", "s2")
    assert json.loads(r[7])["acceptSec"] == 3.1
    bare = row(log.append("pass.up", orderId="o1"), "boot1")
    assert bare[4:7] == (None, None, None)
    assert row(log.append("task.created", taskId="t8", assignee="s3"), "b")[6] == "s3"
    frame = row(
        log.append("ws.in", staff="s1", message={"type": "task.accept", "taskId": "t8"}), "b"
    )
    assert frame[4:7] == ("t8", None, "s1")


def test_offer_never_awaits_and_writes_in_batches() -> None:
    async def go() -> None:
        conn = FakeConn()
        db = EventDB(connector(conn), batch_size=500, flush_sec=0.05, schema=["SELECT 1"])
        log = EventLog(listeners=[db.offer])
        for i in range(1200):
            log.append("task.created", taskId=f"t{i}", table="T1")
        writer = asyncio.create_task(db.run())
        await until(lambda: db.written == 1200)
        writer.cancel()
        assert [len(b) for b in conn.batches] == [500, 500, 200]
        assert [r[2] for b in conn.batches for r in b] == list(range(1, 1201))  # in order
        assert conn.executed == ["SELECT 1"]
        status = db.status()
        assert status["ok"] and status["queued"] == 0 and status["writeMs"]["p50"] >= 0

        log.append("task.done", taskId="t1")  # under a batch: written on the flush timer
        await asyncio.sleep(0)
        writer = asyncio.create_task(db.run())
        await until(lambda: db.written == 1201)
        writer.cancel()

    asyncio.run(go())


def test_an_outage_keeps_the_events_and_writes_them_once_it_is_back() -> None:
    async def go() -> None:
        first, second = FakeConn(fail=1), FakeConn()
        db = EventDB(
            connector(first, second, down=0),
            batch_size=10,
            flush_sec=0.02,
            retry_min_sec=0.01,
            retry_max_sec=0.05,
            schema=[],
        )
        log = EventLog(listeners=[db.offer])
        for i in range(25):
            log.append("task.created", taskId=f"t{i}")
        writer = asyncio.create_task(db.run())
        await until(lambda: db.failures == 1)
        assert db.status()["ok"] is False
        assert "ConnectionResetError" in db.status()["lastError"]
        assert first.closed and db.status()["queued"] == 25  # the failed batch went back
        await until(lambda: db.written == 25, timeout=5)
        writer.cancel()
        seqs = [r[2] for b in second.batches for r in b]
        assert seqs == list(range(1, 26))  # nothing lost, nothing twice
        assert db.status()["ok"] is True

    asyncio.run(go())


def test_database_unreachable_at_boot_then_up() -> None:
    async def go() -> None:
        conn = FakeConn()
        db = EventDB(
            connector(conn, down=2),
            flush_sec=0.02,
            retry_min_sec=0.01,
            retry_max_sec=0.05,
            schema=[],
        )
        db.offer(EventLog().append("app.boot"))
        writer = asyncio.create_task(db.run())
        await until(lambda: db.failures == 2)
        assert (await db.stats())["available"] is False
        await until(lambda: db.written == 1, timeout=5)
        stats = await db.stats()
        writer.cancel()
        assert stats["available"] and stats["accept"][0]["p90Sec"] == 5.0

    asyncio.run(go())


def test_a_full_queue_drops_the_oldest_and_counts_it() -> None:
    db = EventDB(connector(), max_queue=3, schema=[])
    log = EventLog(listeners=[db.offer])
    for i in range(5):
        log.append("e", i=i)
    assert [e.data["i"] for e in db.queue] == [2, 3, 4]
    assert db.status()["dropped"] == 2


@pytest.fixture
def no_observability(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DATABASE_URL", "SENTRY_DSN_BACKEND", "SENTRY_DSN_WEB"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("no_observability")
def test_app_runs_with_no_dsn_and_no_database_url() -> None:
    settings = Settings.from_env()
    assert not (settings.database_url or settings.sentry_dsn_backend or settings.sentry_dsn_web)
    settings = dataclasses.replace(settings, token=TOKEN)
    with TestClient(create_app(settings)) as c:
        health = c.get("/health").json()
        assert health["ok"] and health["eventDb"] == {"enabled": False}
        assert health["sentry"] is False
        assert c.get("/config", headers=H).json() == {"sentry": None}
        r = c.post("/tasks", headers=H, json={"kind": "CHECK", "table": "T1", "assignee": "s1"})
        assert r.status_code == 201
        stats = c.get("/stats", headers=H).json()
        assert stats["history"]["available"] is False
        assert stats["servers"]


def test_config_serves_the_web_dsn_when_set() -> None:
    settings = Settings(token=TOKEN, data_dir=DATA_DIR, sentry_dsn_web="https://k@o1.ingest/2")
    with TestClient(create_app(settings)) as c:
        assert c.get("/config").status_code == 401
        assert c.get("/config", headers=H).json()["sentry"]["dsn"] == "https://k@o1.ingest/2"


def test_app_copies_every_event_to_the_database() -> None:
    conn = FakeConn()
    db = EventDB(connector(conn), flush_sec=0.02, schema=[])
    settings = Settings(token=TOKEN, data_dir=DATA_DIR)
    with TestClient(create_app(settings, eventdb=db)) as c:
        r = c.post("/tasks", headers=H, json={"kind": "CHECK", "table": "T1", "assignee": "s1"})
        task = r.json()["id"]
        deadline = time.monotonic() + 3
        while c.get("/health").json()["eventDb"]["written"] < 1:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        health = c.get("/health").json()["eventDb"]
        assert health["ok"] and health["enabled"]
        assert c.get("/stats", headers=H).json()["history"]["available"] is True
        log = c.app.state.store.events
    written = [r for b in conn.batches for r in b]
    assert len(written) == len(log.since(0))  # shutdown flushed the rest
    assert any(r[3] == "task.queued" and r[4] == task and r[5] == "T1" for r in written)
