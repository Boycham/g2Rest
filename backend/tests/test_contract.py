"""The pydantic mirror of glasses/src/contract.ts, and that the backend stays inside it."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from app import contract
from app.contract import ContractError, check_backend, parse_glasses
from app.data import Floor, Menu
from app.events import EventLog
from app.orders import OrderBook
from app.tasks import TaskBook


def strip_to(model: type[BaseModel], message: dict[str, Any]) -> dict[str, Any]:
    """Drop the keys contract.ts does not know, recursively, as parse.ts does on the glasses."""
    known = model.model_fields
    out: dict[str, Any] = {}
    for key, value in message.items():
        if key not in known:
            continue
        ann = known[key].annotation
        if isinstance(value, dict) and isinstance(ann, type) and issubclass(ann, BaseModel):
            out[key] = strip_to(ann, value)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            inner = ann.__args__[0]  # type: ignore[union-attr]
            out[key] = [strip_to(inner, v) for v in value]
        else:
            out[key] = value
    return out


BASE_FOR = {
    "task.assigned": contract.TaskAssigned,
    "task.updated": contract.TaskUpdated,
    "order.draft": contract.OrderDraft,
    "order.readback": contract.OrderReadback,
    "alert": contract.Alert,
    "floor.state": contract.FloorState,
}


@pytest.fixture
def everything_the_backend_sends(menu: Menu, floor: Floor) -> list[dict[str, Any]]:
    events = EventLog()
    book = TaskBook(floor, events, escalation_sec=30)
    task, out = book.create(
        "RUN",
        "T1",
        now=0,
        items=[{"qty": 2, "dish": "halibut", "seats": [1, 3]}],
        allergies=[{"allergen": "SHELLFISH", "seats": [3]}],
        notes=["VIP"],
    )
    msgs = [o.message for o in out]
    for t in (0, 30, 60):
        book.mark_sent(task.id, now=t)
        msgs += [o.message for o in book.tick(now=t + 30)]  # ends with the manager alert
    msgs += [o.message for o in book.done(task.id, now=91)]  # cleared alert
    orders = OrderBook(menu, set(floor.tables))
    result, order = orders.dispatch(
        "add_item", {"table": "T1", "seat": 1, "dish": "halibut", "alterations": ["no butter"]}
    )
    assert order is not None and result["status"] == "ok"
    orders.dispatch("set_allergy", {"table": "T1", "seat": 1, "allergen": "shellfish"})
    msgs.append(order.draft_wire())
    result, _ = orders.dispatch("confirm_order", {"table": "T1"})
    msgs.append(
        {
            "type": "order.readback",
            "orderId": order.id,
            "action": result["action"],
            "text": result["readback"],
        }
    )
    msgs.append(
        {
            "type": "floor.state",
            "tables": [
                {"table": t.id, "status": "empty", "sinceSec": 0, "x": t.x, "y": t.y, "urgency": 0}
                for t in floor.tables.values()
            ],
        }
    )
    return msgs


def test_every_outbound_message_fits_the_extended_contract(
    everything_the_backend_sends: list[dict[str, Any]],
) -> None:
    types = {m["type"] for m in everything_the_backend_sends}
    assert types == set(BASE_FOR)
    for msg in everything_the_backend_sends:
        check_backend(msg)


def test_contract_ts_parses_what_we_send_once_extras_are_dropped(
    everything_the_backend_sends: list[dict[str, Any]],
) -> None:
    for msg in everything_the_backend_sends:
        base = BASE_FOR[msg["type"]]
        base.model_validate(strip_to(base, msg))


def test_wire_state_is_one_of_the_four_glasses_states() -> None:
    from app.tasks import WIRE_STATE

    assert set(WIRE_STATE.values()) == {"assigned", "accepted", "done", "bounced"}


def test_outbound_typo_is_caught_before_it_reaches_a_socket() -> None:
    with pytest.raises(ContractError, match="task.state"):
        check_backend(
            {
                "type": "task.assigned",
                "task": {
                    "id": "t",
                    "kind": "RUN",
                    "table": "T1",
                    "items": [],
                    "allergies": [],
                    "notes": [],
                    "state": "sent",
                    "assignee": "s1",
                    "priority": 0,
                    "createdAt": "",
                },
            }
        )
    with pytest.raises(ContractError, match="sinceSecs"):
        check_backend({"type": "alert", "id": "a", "level": "warn", "text": "x", "sinceSecs": 1})


@pytest.mark.parametrize(
    "raw",
    [
        '{"type": "task.accept", "taskId": "t1"}',
        '{"type": "task.done", "taskId": "t1"}',
        '{"type": "task.bounce", "taskId": "t1"}',
        '{"type": "capture.start", "captureId": "c1"}',
        '{"type": "capture.start", "captureId": "c1", "table": "T2"}',
        '{"type": "capture.stop", "captureId": "c1"}',
        '{"type": "order.confirm", "orderId": "o1"}',
        '{"type": "order.cancel_confirm", "orderId": "o1"}',
    ],
)
def test_parses_every_glasses_message(raw: str) -> None:
    msg = parse_glasses(raw)
    assert msg.type == json.loads(raw)["type"]


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        ("not json", "message"),
        ('{"taskId": "t1"}', "type"),
        ('{"type": "task.accept"}', "taskId"),
        ('{"type": "task.accept", "task_id": "t1"}', "task_id"),
        ('{"type": "task.accept", "taskId": 7}', "taskId"),
        ('{"type": "task.yeet", "taskId": "t1"}', "type"),
        ('{"type": "capture.audio"}', "type"),
    ],
)
def test_rejects_off_contract_frames_with_the_field_named(raw: str, why: str) -> None:
    with pytest.raises(ContractError, match=why):
        parse_glasses(raw)


def test_audio_format_matches_contract_ts() -> None:
    assert contract.CAPTURE_AUDIO_FORMAT == {
        "sampleRate": 16000,
        "bitsPerSample": 16,
        "channels": 1,
        "frameBytes": 3200,
    }
