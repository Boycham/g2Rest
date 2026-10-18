"""Tiger Data (TimescaleDB) copy of the event log: batched, off the hub's path, optional.

The in-memory `EventLog` stays the source of truth. `offer()` (an EventLog listener) only appends
the event to a bounded queue, so the hub never waits on the database. `run()` is its own task:
it connects, applies `schema.sql`, and writes batches with one `executemany` each. When the
database is down it keeps the unsent events (past `max_queue` the oldest are dropped and
counted), reconnects with backoff, and `status()` says so for `GET /health`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from app.events import Event

log = logging.getLogger("fs.eventdb")
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
INSERT = (
    "INSERT INTO fs_events (time, boot, seq, type, task, table_id, staff, payload)"
    " VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)"
)
AGGREGATES = {"accept": "fs_accept_latency", "ticket": "fs_ticket_time"}
STATS_SQL = """
SELECT staff, kind, sum(n)::int AS n, sum(total_sec) / sum(n) AS avg_sec, max(max_sec) AS max_sec,
       approx_percentile(0.5, rollup(pct)) AS p50_sec,
       approx_percentile(0.9, rollup(pct)) AS p90_sec
FROM {view} WHERE bucket > now() - $1::interval
GROUP BY staff, kind ORDER BY staff, kind
"""


class Conn(Protocol):
    """The slice of an asyncpg connection we use, so tests can pass a fake."""

    async def execute(self, query: str, *args: Any) -> str: ...
    async def executemany(self, query: str, args: list[tuple[Any, ...]]) -> None: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def close(self) -> None: ...


Connect = Callable[[], Awaitable[Conn]]


def asyncpg_connect(url: str, timeout_sec: float = 5.0) -> Connect:
    async def connect() -> Conn:
        import asyncpg  # only needed when DATABASE_URL is set

        return await asyncpg.connect(url, timeout=timeout_sec, command_timeout=timeout_sec)

    return connect


def schema_statements(path: Path = SCHEMA_PATH) -> list[str]:
    lines = [ln for ln in path.read_text().splitlines() if not ln.lstrip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";\n") if s.strip().rstrip(";").strip()]


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def row(event: Event, boot: str) -> tuple[Any, ...]:
    d = event.data
    return (
        datetime.fromisoformat(event.at),
        boot,
        event.seq,
        event.type,
        _text(d.get("taskId")),
        _text(d.get("table")),
        _text(d.get("staff") or d.get("assignee")),
        json.dumps(d, default=str),
    )


class EventDB:
    def __init__(
        self,
        connect: Connect,
        *,
        boot: str | None = None,
        batch_size: int = 500,
        flush_sec: float = 0.25,
        max_queue: int = 50_000,
        retry_max_sec: float = 30.0,
        timeout_sec: float = 5.0,
        schema: list[str] | None = None,
    ) -> None:
        self.connect = connect
        self.boot = boot or uuid.uuid4().hex[:12]
        self.batch_size = batch_size
        self.flush_sec = flush_sec
        self.max_queue = max_queue
        self.retry_max_sec = retry_max_sec
        self.timeout_sec = timeout_sec
        self.schema = schema_statements() if schema is None else schema
        self.queue: deque[Event] = deque()
        self.conn: Conn | None = None
        self.lock = asyncio.Lock()  # one connection: a /stats read waits for the batch in flight
        self.ok = False
        self.written = self.dropped = self.batches = self.failures = 0
        self.last_error: str | None = None
        self.schema_errors: list[str] = []
        self.last_write_at: float | None = None
        self.write_ms: deque[float] = deque(maxlen=500)
        self._wake = asyncio.Event()

    # ---------- the hub's side: O(1), never raises, never awaits ----------

    def offer(self, event: Event) -> None:
        if len(self.queue) >= self.max_queue:
            self.queue.popleft()
            self.dropped += 1
        self.queue.append(event)
        if len(self.queue) >= self.batch_size:
            self._wake.set()

    # ---------- the writer task ----------

    async def run(self) -> None:
        delay = 1.0
        while True:
            try:
                if self.conn is None:
                    await self._open()
                    delay = 1.0
                if await self.flush() < self.batch_size:
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), self.flush_sec)
                    except TimeoutError:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - an outage must never stop the backend
                await self._down(e)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.retry_max_sec)

    async def flush(self) -> int:
        """Write one batch. On failure the batch goes back to the front of the queue."""
        if not self.queue or self.conn is None:
            return 0
        batch = [self.queue.popleft() for _ in range(min(len(self.queue), self.batch_size))]
        t0 = time.perf_counter()
        try:
            rows = [row(e, self.boot) for e in batch]
            async with self.lock:
                await asyncio.wait_for(self.conn.executemany(INSERT, rows), self.timeout_sec)
        except BaseException:
            self._requeue(batch)
            raise
        self.write_ms.append((time.perf_counter() - t0) * 1000)
        self.written += len(batch)
        self.batches += 1
        self.last_write_at = time.time()
        if not self.ok:
            log.info("[fs] event db up, %d queued", len(self.queue))
        self.ok = True
        return len(batch)

    async def close(self, timeout_sec: float = 3.0) -> None:
        """Shutdown: one last try to write what's queued, then close."""
        try:
            async with asyncio.timeout(timeout_sec):
                while self.conn is not None and self.queue:
                    await self.flush()
        except Exception as e:  # noqa: BLE001
            log.warning("[fs] event db: %d events not written at shutdown (%r)", len(self.queue), e)
        await self._close_conn()

    def _requeue(self, batch: list[Event]) -> None:
        self.queue.extendleft(reversed(batch))
        while len(self.queue) > self.max_queue:
            self.queue.popleft()
            self.dropped += 1

    async def _open(self) -> None:
        conn = await asyncio.wait_for(self.connect(), self.timeout_sec)
        self.schema_errors = []
        for statement in self.schema:
            try:
                await asyncio.wait_for(conn.execute(statement), self.timeout_sec * 4)
            except Exception as e:  # noqa: BLE001 - a broken aggregate must not stop the log
                self.schema_errors.append(f"{statement.split(chr(10))[0][:60]}: {e}"[:200])
        if self.schema_errors:
            log.warning("[fs] event db schema: %s", "; ".join(self.schema_errors))
        self.conn = conn

    async def _down(self, e: BaseException) -> None:
        self.failures += 1
        self.last_error = f"{type(e).__name__}: {e}"[:200]
        if self.ok or self.failures == 1:
            log.warning("[fs] event db down, %d queued: %s", len(self.queue), self.last_error)
        self.ok = False
        await self._close_conn()

    async def _close_conn(self) -> None:
        conn, self.conn = self.conn, None
        if conn is not None:
            try:
                await asyncio.wait_for(conn.close(), 2.0)
            except Exception:  # noqa: BLE001, S110 - already broken
                pass

    # ---------- reads ----------

    def status(self) -> dict[str, Any]:
        ms = sorted(self.write_ms)
        pick = (lambda q: round(ms[min(len(ms) - 1, int(q * len(ms)))], 1)) if ms else None
        return {
            "enabled": True,
            "ok": self.ok and self.conn is not None,
            "queued": len(self.queue),
            "written": self.written,
            "dropped": self.dropped,
            "failures": self.failures,
            "lastError": self.last_error,
            "lastWriteAgoSec": (
                round(time.time() - self.last_write_at, 1) if self.last_write_at else None
            ),
            "writeMs": pick and {"p50": pick(0.5), "p95": pick(0.95), "max": round(ms[-1], 1)},
            "schemaErrors": self.schema_errors,
        }

    async def stats(self, hours: float = 24.0) -> dict[str, Any]:
        """Accept latency and ticket time per server and task kind, from the continuous
        aggregates. Never raises: an outage comes back as `available: false`."""
        if self.conn is None:
            return {"available": False, "reason": self.last_error or "connecting"}
        out: dict[str, Any] = {"available": True, "hours": hours}
        try:
            async with self.lock:
                for key, view in AGGREGATES.items():
                    rows = await asyncio.wait_for(
                        self.conn.fetch(STATS_SQL.format(view=view), timedelta(hours=hours)),
                        self.timeout_sec,
                    )
                    out[key] = [_stat(r) for r in rows]
        except Exception as e:  # noqa: BLE001
            return {"available": False, "reason": f"{type(e).__name__}: {e}"[:200]}
        return out


def _stat(r: Any) -> dict[str, Any]:
    def sec(v: Any) -> float | None:
        return None if v is None else round(float(v), 2)

    return {
        "staff": r["staff"],
        "kind": r["kind"],
        "n": r["n"],
        "avgSec": sec(r["avg_sec"]),
        "p50Sec": sec(r["p50_sec"]),
        "p90Sec": sec(r["p90_sec"]),
        "maxSec": sec(r["max_sec"]),
    }
