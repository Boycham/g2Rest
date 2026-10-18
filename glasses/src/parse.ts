import type {
  Alert,
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

// Runtime checks for what arrives over the socket or out of storage. Anything that
// doesn't match the contract is dropped (and logged by the caller), never rendered.

type Obj = Record<string, unknown>

const KINDS: readonly TaskKind[] = ['RUN', 'CLEAR', 'CHECK', 'SEAT']
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
]

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
    (v.cleared === undefined || typeof v.cleared === 'boolean')
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
