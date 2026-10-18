"""Append-only event log. Nothing is ever edited or removed; readers page with `since`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class Event:
    seq: int
    at: str
    type: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "at": self.at, "type": self.type, "data": self.data}


@dataclass
class EventLog:
    _events: list[Event] = field(default_factory=list)

    def append(self, type: str, **data: Any) -> Event:
        event = Event(len(self._events) + 1, datetime.now(UTC).isoformat(), type, data)
        self._events.append(event)
        return event

    def since(self, seq: int = 0) -> list[Event]:
        return [e for e in self._events if e.seq > seq]

    def of_type(self, type: str) -> list[Event]:
        return [e for e in self._events if e.type == type]

    def __len__(self) -> int:
        return len(self._events)
