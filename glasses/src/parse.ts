import type {
  Alert,
  AlertKind,
  AlertLevel,
  Allergy,
  BackendMessage,
  FloorState,
  TableState,
  TableStatus,
  Task,
  TaskItem,
  TaskKind,
  TaskState,
} from './contract'
import type { Exceptions, OpenAlert } from './exceptions'
import { ROLES, type Role } from './hud'
import type { FloorTable } from './minimap'

// Runtime checks for what arrives over the socket or out of storage. Anything that
// doesn't match the contract is dropped (and logged by the caller), never rendered.

type Obj = Record<string, unknown>

const KINDS: readonly TaskKind[] = ['RUN', 'CLEAR', 'CHECK', 'SEAT', 'ORDER']
const STATES: readonly TaskState[] = ['assigned', 'accepted', 'done', 'bounced']
const LEVELS: readonly AlertLevel[] = ['info', 'warn', 'urgent']
const TABLE_STATUSES: readonly TableStatus[] = ['empty', 'seated', 'ordered', 'waiting', 'eating', 'check']
const BACKEND_TYPES: readonly BackendMessage['type'][] = [
  'task.assigned',
  'task.updated',
  'order.draft',
  'order.readback',
  'alert',
  'floor.state',
  'order.closed',
  'voice.command',
  'voice.mapping',
  'voice.unknown',
  'voice.request',
  'task.rejected',
]
const ALERT_KINDS: readonly AlertKind[] = ['unacked', 'slow', 'course_wait', 'vip', '86']
const INTENTS = ['up', 'down', 'back', 'confirm', 'clip', 'accept', 'decline', 'done', 'handoff', 'nevermind', 'revert', 'menu', 'queue', 'table', 'ramp']
const REJECTED_ACTIONS = ['accept', 'done', 'bounce', 'handoff', 'revert', 'request', 'status']
const REQUEST_KINDS = ['RUN', 'CLEAR', 'CHECK', 'SEAT', 'ORDER']
const CLOSED_STATUSES = ['fired', 'cancelled']

const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)
const isStr = (v: unknown): v is string => typeof v === 'string'
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const isSeats = (v: unknown): v is number[] => Array.isArray(v) && v.every(n => Number.isInteger(n))

function isItem(v: unknown): v is TaskItem {
  return isObj(v) && Number.isInteger(v.qty) && isStr(v.dish) && isSeats(v.seats)
}

function isAllergy(v: unknown): v is Allergy {
  return isObj(v) && isStr(v.allergen) && isSeats(v.seats)
}

export function isTask(v: unknown): v is Task {
  return (
    isObj(v) &&
    isStr(v.id) &&
    KINDS.includes(v.kind as TaskKind) &&
    isStr(v.table) &&
    Array.isArray(v.items) &&
    v.items.every(isItem) &&
    Array.isArray(v.allergies) &&
    v.allergies.every(isAllergy) &&
    Array.isArray(v.notes) &&
    v.notes.every(isStr) &&
    STATES.includes(v.state as TaskState)
  )
}

export function isAlert(v: unknown): v is Alert {
  return (
    isObj(v) &&
    v.type === 'alert' &&
    isStr(v.id) &&
    LEVELS.includes(v.level as AlertLevel) &&
    isStr(v.text) &&
    (v.table === undefined || isStr(v.table)) &&
    (v.sinceSec === undefined || (isNum(v.sinceSec) && v.sinceSec >= 0)) &&
    (v.cleared === undefined || typeof v.cleared === 'boolean') &&
    (v.kind === undefined || ALERT_KINDS.includes(v.kind as AlertKind))
  )
}

export function isTableState(v: unknown): v is TableState {
  return (
    isObj(v) &&
    isStr(v.table) &&
    TABLE_STATUSES.includes(v.status as TableStatus) &&
    isNum(v.sinceSec) &&
    v.sinceSec >= 0 &&
    isNum(v.x) &&
    isNum(v.y) &&
    Number.isInteger(v.urgency) &&
    (v.urgency as number) >= 0 &&
    (v.urgency as number) <= 4
  )
}

function isFloorState(v: Obj): v is Obj & FloorState {
  return Array.isArray(v.tables) && v.tables.every(isTableState)
}

function isVoiceRequest(v: Record<string, unknown>): boolean {
  const optStr = (x: unknown) => x === undefined || isStr(x)
  const kind = v.kind === undefined || REQUEST_KINDS.includes(v.kind as string)
  const status = v.status === undefined || TABLE_STATUSES.includes(v.status as TableStatus)
  const something = v.kind !== undefined || v.status !== undefined || isStr(v.reason)
  return (
    isStr(v.table) && kind && status && something && (v.vip === undefined || typeof v.vip === 'boolean') &&
    optStr(v.note) && optStr(v.reason) && (v.source === 'clip' || v.source === 'voice')
  )
}

/** Messages the glasses render are fully checked; the others only by type until they're used. */
export function parseBackendMessage(raw: string): BackendMessage | null {
  let v: unknown
  try {
    v = JSON.parse(raw)
  } catch {
    return null
  }
  if (!isObj(v) || !BACKEND_TYPES.includes(v.type as BackendMessage['type'])) return null
  if ((v.type === 'task.assigned' || v.type === 'task.updated') && !isTask(v.task)) return null
  if (v.type === 'alert' && !isAlert(v)) return null
  if (v.type === 'floor.state' && !isFloorState(v)) return null
  if (v.type === 'order.closed' && !(isStr(v.orderId) && CLOSED_STATUSES.includes(v.status as string))) return null
  const optStr = (x: unknown) => x === undefined || isStr(x)
  if (
    v.type === 'voice.command' &&
    !(INTENTS.includes(v.intent as string) && optStr(v.name) && optStr(v.table) && optStr(v.was) && optStr(v.reason) && (v.toggle === undefined || v.toggle === 'on' || v.toggle === 'off'))
  ) {
    return null
  }
  if (
    v.type === 'task.rejected' &&
    !((v.taskId === null || isStr(v.taskId)) && REJECTED_ACTIONS.includes(v.action as string) && isStr(v.reason))
  ) {
    return null
  }
  if (v.type === 'voice.request' && !isVoiceRequest(v)) return null
  if (v.type === 'voice.mapping' && !isStr(v.words)) return null
  if (v.type === 'voice.unknown' && !(isStr(v.words) && (v.reason === undefined || isStr(v.reason)))) return null
  return v as unknown as BackendMessage
}

export function parseTaskList(raw: string): Task[] | null {
  try {
    const v: unknown = JSON.parse(raw)
    return Array.isArray(v) && v.every(isTask) ? v : null
  } catch {
    return null
  }
}

export function parseRole(raw: string): Role | null {
  return ROLES.includes(raw as Role) ? (raw as Role) : null
}

function isOpenAlert(v: unknown): v is OpenAlert {
  return (
    isObj(v) &&
    isStr(v.id) &&
    LEVELS.includes(v.level as AlertLevel) &&
    isStr(v.text) &&
    (v.table === undefined || isStr(v.table)) &&
    (v.since === null || isNum(v.since)) &&
    isNum(v.seq)
  )
}

function isExceptions(v: unknown): v is Exceptions {
  return (
    isObj(v) &&
    Array.isArray(v.open) &&
    v.open.every(isOpenAlert) &&
    isObj(v.dismissed) &&
    Object.values(v.dismissed).every(l => LEVELS.includes(l as AlertLevel)) &&
    isNum(v.nextSeq)
  )
}

function isFloorTable(v: unknown): v is FloorTable {
  return (
    isObj(v) &&
    isStr(v.table) &&
    TABLE_STATUSES.includes(v.status as TableStatus) &&
    isNum(v.since) &&
    isNum(v.x) &&
    isNum(v.y) &&
    Number.isInteger(v.urgency)
  )
}

/** The manager HUD's cached exceptions and floor, from SDK storage. */
export function parseManagerCache(raw: string): { exceptions: Exceptions; tables: FloorTable[] } | null {
  try {
    const v: unknown = JSON.parse(raw)
    if (!isObj(v) || !isExceptions(v.exceptions) || !Array.isArray(v.tables) || !v.tables.every(isFloorTable)) return null
    return { exceptions: v.exceptions, tables: v.tables }
  } catch {
    return null
  }
}
