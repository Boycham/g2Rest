"""Python mirror of `glasses/src/contract.ts` (signed off at Sync 1), checked with pydantic.

Section 1 is the contract as first written in contract.ts plus the voice fields (proposalId,
order.reject, the order.draft extras): same message types,
same camelCase field names, same shapes, `extra="forbid"` so a drift on either side fails a
test instead of silently passing. Section 2 holds the backend's requested additions
(CONTRACT.md "Contract changes requested"); every outbound message is validated against
them before it goes down a socket, and a test proves the base models still parse them.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

# ---------- 1. contract.ts, verbatim ----------


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


TaskKind = Literal["RUN", "CLEAR", "CHECK", "SEAT", "ORDER"]
TaskState = Literal["assigned", "accepted", "done", "bounced"]
TableStatus = Literal["empty", "seated", "ordered", "waiting", "eating", "check"]
AlertLevel = Literal["info", "warn", "urgent"]


class TaskItem(Strict):
    qty: int
    dish: str
    seats: list[int]


class Allergy(Strict):
    allergen: str
    seats: list[int]


class Task(Strict):
    id: str
    kind: TaskKind
    table: str
    items: list[TaskItem]
    allergies: list[Allergy]
    notes: list[str]
    state: TaskState


class OrderLine(Strict):
    seat: int
    qty: int
    dish: str
    alterations: list[str]
    flagged: list[str]


class TableState(Strict):
    table: str
    status: TableStatus
    sinceSec: int


# glasses -> backend


class TaskAccept(Strict):
    type: Literal["task.accept"]
    taskId: str


class TaskDone(Strict):
    type: Literal["task.done"]
    taskId: str


class TaskBounce(Strict):
    type: Literal["task.bounce"]
    taskId: str


class CaptureStart(Strict):
    type: Literal["capture.start"]
    captureId: str


CAPTURE_AUDIO_FORMAT = {"sampleRate": 16000, "bitsPerSample": 16, "channels": 1, "frameBytes": 3200}


class CaptureStop(Strict):
    type: Literal["capture.stop"]
    captureId: str


class OrderConfirm(Strict):
    type: Literal["order.confirm"]
    orderId: str
    proposalId: str | None = None


class OrderCancelConfirm(Strict):
    type: Literal["order.cancel_confirm"]
    orderId: str
    proposalId: str | None = None


class OrderReject(Strict):
    type: Literal["order.reject"]
    orderId: str
    proposalId: str


GlassesJsonMessage = Annotated[
    TaskAccept
    | TaskDone
    | TaskBounce
    | CaptureStart
    | CaptureStop
    | OrderConfirm
    | OrderCancelConfirm
    | OrderReject,
    Field(discriminator="type"),
]

# backend -> glasses


class TaskAssigned(Strict):
    type: Literal["task.assigned"]
    task: Task


class TaskUpdated(Strict):
    type: Literal["task.updated"]
    task: Task


class PendingProposal(Strict):
    id: str
    action: Literal["remove", "cancel", "confirm"]
    text: str


class OrderDraft(Strict):
    type: Literal["order.draft"]
    orderId: str
    captureId: str
    table: str | None
    lines: list[OrderLine]
    allergies: list[Allergy]
    status: Literal["draft", "sent", "cancelled"] | None = None
    pending: list[PendingProposal] | None = None
    voice: Literal["idle", "connecting", "listening", "processing", "offline"] | None = None
    notice: str | None = None
    notes: list[str] | None = None
    uncertain: list[str] | None = None


class OrderReadback(Strict):
    type: Literal["order.readback"]
    orderId: str
    action: Literal["confirm", "cancel"]
    text: str


class Alert(Strict):
    type: Literal["alert"]
    id: str
    level: AlertLevel
    text: str


class FloorState(Strict):
    type: Literal["floor.state"]
    tables: list[TableState]


BackendMessage = Annotated[
    TaskAssigned | TaskUpdated | OrderDraft | OrderReadback | Alert | FloorState,
    Field(discriminator="type"),
]


# ---------- 2. the backend's additions (in contract.ts since Sync 1) ----------


class TaskExt(Task):
    """+ who holds it, run priority, creation time. The glasses may ignore all three."""

    assignee: str
    priority: float
    createdAt: str


class TaskAssignedExt(TaskAssigned):
    task: TaskExt


class TaskUpdatedExt(TaskUpdated):
    task: TaskExt


class TableStateExt(TableState):
    """+ the manager-HUD fields from origin/devin/manager-hud."""

    x: float
    y: float
    urgency: int = Field(ge=0, le=4)


class FloorStateExt(FloorState):
    tables: list[TableStateExt]


class AlertExt(Alert):
    """+ the manager-HUD fields from origin/devin/manager-hud."""

    table: str | None = None
    sinceSec: int | None = None
    cleared: bool | None = None


class OrderClosed(Strict):
    """New: result of order.confirm / order.cancel_confirm, so the glasses drop the draft."""

    type: Literal["order.closed"]
    orderId: str
    status: Literal["fired", "cancelled"]


class CaptureStartExt(CaptureStart):
    """+ optional table, when the glasses know which card the server was looking at."""

    table: str | None = None
    mode: Literal["stream", "clip"] | None = None


BackendMessageExt = Annotated[
    TaskAssignedExt
    | TaskUpdatedExt
    | OrderDraft
    | OrderReadback
    | AlertExt
    | FloorStateExt
    | OrderClosed,
    Field(discriminator="type"),
]
GlassesJsonMessageExt = Annotated[
    TaskAccept
    | TaskDone
    | TaskBounce
    | CaptureStartExt
    | CaptureStop
    | OrderConfirm
    | OrderCancelConfirm
    | OrderReject,
    Field(discriminator="type"),
]

glasses_messages: TypeAdapter[Any] = TypeAdapter(GlassesJsonMessage)
glasses_messages_ext: TypeAdapter[Any] = TypeAdapter(GlassesJsonMessageExt)
backend_messages: TypeAdapter[Any] = TypeAdapter(BackendMessage)
backend_messages_ext: TypeAdapter[Any] = TypeAdapter(BackendMessageExt)


class ContractError(ValueError):
    """A frame that does not match the contract. Logged and dropped, never raised to a socket."""


def parse_glasses(raw: str | bytes) -> Any:
    """Inbound JSON text frame -> one of the glasses message models (extended set)."""
    try:
        return glasses_messages_ext.validate_json(raw)
    except ValidationError as e:
        first = e.errors()[0]
        raise ContractError(
            f"{'.'.join(map(str, first['loc'])) or 'message'}: {first['msg']}"
        ) from e


def check_backend(message: dict[str, Any]) -> None:
    """Outbound dict -> raises ContractError unless it matches the extended backend contract."""
    try:
        backend_messages_ext.validate_python(message)
    except ValidationError as e:
        first = e.errors()[0]
        raise ContractError(
            f"{'.'.join(map(str, first['loc'])) or 'message'}: {first['msg']}"
        ) from e
