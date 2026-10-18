import type { Allergy, BackendMessage, Task, TaskItem, TaskKind, TaskState } from './contract'

// Runtime checks for what arrives over the socket or out of storage. Anything that
// doesn't match the contract is dropped (and logged by the caller), never rendered.

type Obj = Record<string, unknown>

const KINDS: readonly TaskKind[] = ['RUN', 'CLEAR', 'CHECK', 'SEAT']
const STATES: readonly TaskState[] = ['assigned', 'accepted', 'done', 'bounced']
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

/** Task messages are fully checked; the others only by type until the glasses use them. */
export function parseBackendMessage(raw: string): BackendMessage | null {
  let v: unknown
  try {
    v = JSON.parse(raw)
  } catch {
    return null
  }
  if (!isObj(v) || !BACKEND_TYPES.includes(v.type as BackendMessage['type'])) return null
  if ((v.type === 'task.assigned' || v.type === 'task.updated') && !isTask(v.task)) return null
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
