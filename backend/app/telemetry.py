"""Sentry for the backend: errors, tracing and Logs. Off unless SENTRY_DSN_BACKEND is set.

Every helper here is a cheap no-op when Sentry is off, so the hub calls them unconditionally.
Trace context travels as `{"sentryTrace": ..., "baggage": ...}`: the web pages send it as HTTP
headers, a task keeps the context it was created in (so the glasses' accept continues the
organizer's dispatch trace), and the optional `trace` field proposed in CONTRACT.md §8.11
carries it over the WebSocket.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

log = logging.getLogger("fs.telemetry")
Trace = dict[str, str]


def init_sentry(
    dsn: str, environment: str = "dev", traces_rate: float = 1.0, **options: Any
) -> bool:
    if not dsn:
        log.info("[fs] Sentry off (no SENTRY_DSN_BACKEND)")
        return False

    def sampler(ctx: dict[str, Any]) -> float:
        # One transaction per open socket would hold every frame of a whole shift; each inbound
        # frame gets its own transaction instead (`frame()`).
        if (ctx.get("asgi_scope") or {}).get("type") == "websocket":
            return 0.0
        return traces_rate

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sampler=sampler,
        enable_logs=True,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            LoggingIntegration(level=logging.INFO, sentry_logs_level=logging.INFO),
        ],
        **options,
    )
    logging.getLogger("fs").setLevel(logging.INFO)
    log.info("[fs] Sentry on (%s)", environment)
    return True


def current_trace() -> Trace | None:
    """The active span's trace context, to store on a task or send on the wire."""
    if sentry_sdk.get_current_span() is None:
        return None
    trace = {"sentryTrace": sentry_sdk.get_traceparent() or ""}
    baggage = sentry_sdk.get_baggage()
    if baggage:
        trace["baggage"] = baggage
    return trace if trace["sentryTrace"] else None


@contextmanager
def span(op: str, name: str, **data: Any) -> Iterator[None]:
    """A child span of whatever is running; dropped by the SDK when nothing is."""
    with sentry_sdk.start_span(op=op, name=name) as s:
        for key, value in data.items():
            s.set_data(key, value)
        yield


@contextmanager
def root(op: str, name: str, trace: Trace | None = None, **data: Any) -> Iterator[None]:
    """A span of its own for work no request started (a glasses frame, the ticker):
    a child if something is already running, else a new transaction that continues `trace`."""
    if trace is None and sentry_sdk.get_current_span() is not None:
        with span(op, name, **data):
            yield
        return
    with sentry_sdk.isolation_scope():
        headers = {}
        if trace and trace.get("sentryTrace"):
            headers = {"sentry-trace": trace["sentryTrace"], "baggage": trace.get("baggage", "")}
        tx = sentry_sdk.continue_trace(headers, op=op, name=name)
        with sentry_sdk.start_transaction(tx) as t:
            for key, value in data.items():
                t.set_data(key, value)
            yield
