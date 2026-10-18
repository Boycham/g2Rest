// Floor Sense glasses <-> backend message contract.
//
// Signed off by both lanes at Sync 1; backend/app/contract.py is the pydantic mirror and
// backend/CONTRACT.md the prose. Change it only by agreement in a PR.
//
// Transport: one WebSocket per glasses session. Every message is a JSON text frame
// `{ "type": ..., ... }`, except `capture.audio`, which is a binary frame.

// ---------- shared shapes ----------

export type TaskKind = 'RUN' | 'CLEAR' | 'CHECK' | 'SEAT'

/** Lifecycle of a task as the backend sees it. */
export type TaskState = 'assigned' | 'accepted' | 'done' | 'bounced'

export interface TaskItem {
  qty: number
  dish: string
  /** Seat numbers at the table, e.g. [1, 3]. Empty when not seat-specific. */
  seats: number[]
}

export interface Allergy {
  /** Uppercase allergen name, e.g. "SHELLFISH". */
  allergen: string
  seats: number[]
}

export interface Task {
  id: string
  kind: TaskKind
  /** Table label as shown to staff, e.g. "T12". */
  table: string
  items: TaskItem[]
  allergies: Allergy[]
  /** Short free-text notes, one per line, e.g. "VIP: anniversary". */
  notes: string[]
  state: TaskState
  /** Staff id holding the task, e.g. "s1". Always sent by the backend; the glasses ignore it. */
  assignee?: string
  /** Run priority score (higher first). Always sent by the backend; the glasses ignore it. */
  priority?: number
  /** ISO-8601 UTC creation time. Always sent by the backend; the glasses ignore it. */
  createdAt?: string
}

export interface OrderLine {
  seat: number
  qty: number
  dish: string
  /** Alterations that passed the menu guard, e.g. "no onions". */
  alterations: string[]
  /** Alterations the guard rejected; shown flagged, never applied. */
  flagged: string[]
}

export type TableStatus = 'empty' | 'seated' | 'ordered' | 'waiting' | 'eating' | 'check'

export interface TableState {
  table: string
  status: TableStatus
  /** Seconds in the current status. */
  sinceSec: number
  /**
   * The table's position on the floor plan, in any unit with x to the right and y down.
   * The glasses fit the floor's bounding box to the display.
   */
  x: number
  y: number
  /**
   * How much the table needs the manager, 0 (fine) to 4 (now). Decided by the backend's
   * exception rules; the glasses map it to brightness.
   */
  urgency: number
}

// ---------- glasses -> backend ----------

export interface TaskAccept {
  type: 'task.accept'
  taskId: string
}

export interface TaskDone {
  type: 'task.done'
  taskId: string
}

export interface TaskBounce {
  type: 'task.bounce'
  taskId: string
}

export interface CaptureStart {
  type: 'capture.start'
  /** Generated on the glasses; ties audio frames and the stop to this capture. */
  captureId: string
  /** Table of the card on screen, when known; otherwise the backend uses the server's current card. */
  table?: string
}

/**
 * `capture.audio` is a binary WebSocket frame, not JSON: raw mic PCM, 16 kHz, signed
 * 16-bit little-endian, mono, normally 3200 bytes (100 ms). It belongs to the one
 * capture opened by the last `capture.start` on this socket.
 */
export type CaptureAudio = ArrayBuffer

export const CAPTURE_AUDIO_FORMAT = {
  sampleRate: 16000,
  bitsPerSample: 16,
  channels: 1,
  frameBytes: 3200,
} as const

export interface CaptureStop {
  type: 'capture.stop'
  captureId: string
}

/** Tap on the draft. With `proposalId`: apply that pending change. Without: send the order. */
export interface OrderConfirm {
  type: 'order.confirm'
  orderId: string
  /** The pending proposal the tap applies. */
  proposalId?: string
}

export interface OrderCancelConfirm {
  type: 'order.cancel_confirm'
  orderId: string
  /** The pending cancel proposal the tap applies. */
  proposalId?: string
}

/** Swipe up on a pending proposal drops it; nothing changes. */
export interface OrderReject {
  type: 'order.reject'
  orderId: string
  proposalId: string
}

export type GlassesJsonMessage =
  | TaskAccept
  | TaskDone
  | TaskBounce
  | CaptureStart
  | CaptureStop
  | OrderConfirm
  | OrderCancelConfirm
  | OrderReject

// ---------- backend -> glasses ----------

export interface TaskAssigned {
  type: 'task.assigned'
  task: Task
}

/** Full replacement of a task the glasses already have. */
export interface TaskUpdated {
  type: 'task.updated'
  task: Task
}

/** A destructive change the agent asked for, waiting for a tap. */
export interface PendingProposal {
  id: string
  action: 'remove' | 'cancel' | 'confirm'
  /** Ready to show, e.g. "REMOVE s2 salmon?". */
  text: string
}

/** `connecting` until Scribe and the agent answer. */
export type VoiceState = 'idle' | 'connecting' | 'listening' | 'offline'

/** Full replacement of the order being taken, sent after every change. */
export interface OrderDraft {
  type: 'order.draft'
  orderId: string
  captureId: string
  table: string | null
  lines: OrderLine[]
  allergies: Allergy[]
  /** `sent` / `cancelled` only after the server's tap. */
  status?: 'draft' | 'sent' | 'cancelled'
  /** Oldest first; only the first is shown and answered by tap / swipe up. */
  pending?: PendingProposal[]
  /** Speech pipeline state, `offline` shows VOICE OFFLINE. */
  voice?: VoiceState
  /** One-line reason the last tool call was refused, e.g. "s2 has no soup". */
  notice?: string | null
}

/** The agent proposes sending or cancelling; only a tap on the glasses does it. */
export interface OrderReadback {
  type: 'order.readback'
  orderId: string
  action: 'confirm' | 'cancel'
  text: string
}

export type AlertLevel = 'info' | 'warn' | 'urgent'

/** A manager exception. Re-sending the same `id` replaces it. */
export interface Alert {
  type: 'alert'
  id: string
  level: AlertLevel
  /**
   * One short line, e.g. "T4 waiting {elapsed} on mains". `{elapsed}` is replaced on the
   * glasses by a timer that ticks locally from `sinceSec` ("45s", "14m").
   */
  text: string
  /** Table label the exception is about, e.g. "T4". */
  table?: string
  /** Seconds the condition has lasted when this message is sent; starts the local timer. */
  sinceSec?: number
  /** True once the condition is resolved; the glasses drop the alert. */
  cleared?: boolean
}

/**
 * The answer to the tap that sends or cancels an order (`order.confirm` /
 * `order.cancel_confirm` without a `proposalId`): the glasses leave the draft screen.
 */
export interface OrderClosed {
  type: 'order.closed'
  orderId: string
  status: 'fired' | 'cancelled'
}

/** A full snapshot of every table (not a diff); sent on connect and on every change. */
export interface FloorState {
  type: 'floor.state'
  tables: TableState[]
}

export type BackendMessage =
  | TaskAssigned
  | TaskUpdated
  | OrderDraft
  | OrderReadback
  | Alert
  | FloorState
  | OrderClosed
