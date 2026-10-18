// Floor Sense glasses <-> backend message contract.
//
// PROPOSED, needs Coder A sign-off. Written by the glasses lane before the backend
// existed; do not treat it as frozen until Coder A agrees in the PR.
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
  /** PROPOSED (voice capture): the pending proposal the tap applies. */
  proposalId?: string
}

export interface OrderCancelConfirm {
  type: 'order.cancel_confirm'
  orderId: string
  /** PROPOSED (voice capture): the pending cancel proposal the tap applies. */
  proposalId?: string
}

/** PROPOSED (voice capture): swipe up on a pending proposal drops it; nothing changes. */
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

/** PROPOSED (voice capture): a destructive change the agent asked for, waiting for a tap. */
export interface PendingProposal {
  id: string
  action: 'remove' | 'cancel' | 'confirm'
  /** Ready to show, e.g. "REMOVE s2 salmon?". */
  text: string
}

/** PROPOSED (voice capture): `connecting` until Scribe and the agent answer. */
export type VoiceState = 'idle' | 'connecting' | 'listening' | 'offline'

/** Full replacement of the order being taken, sent after every change. */
export interface OrderDraft {
  type: 'order.draft'
  orderId: string
  captureId: string
  table: string | null
  lines: OrderLine[]
  allergies: Allergy[]
  /** PROPOSED: `sent` / `cancelled` only after the server's tap. */
  status?: 'draft' | 'sent' | 'cancelled'
  /** PROPOSED: oldest first; only the first is shown and answered by tap / swipe up. */
  pending?: PendingProposal[]
  /** PROPOSED: speech pipeline state, `offline` shows VOICE OFFLINE. */
  voice?: VoiceState
  /** PROPOSED: one-line reason the last tool call was refused, e.g. "s2 has no soup". */
  notice?: string | null
}

/** The agent proposes sending or cancelling; only a tap on the glasses does it. */
export interface OrderReadback {
  type: 'order.readback'
  orderId: string
  action: 'confirm' | 'cancel'
  text: string
}

export interface Alert {
  type: 'alert'
  id: string
  level: 'info' | 'warn' | 'urgent'
  text: string
}

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
