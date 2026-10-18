import type { EvenAppBridge } from '@evenrealities/even_hub_sdk'
import type { GlassesJsonMessage, Task } from './contract'
import { upsertTask, type Queue } from './tasks'
import { log } from './log'

// A backend that restarts (or missed gestures made offline) replays `task.assigned` for
// tasks the wearer already accepted or finished. The glasses keep the further-along
// local state and re-send that gesture, so nothing is lost and nothing comes back.

/** Ids the wearer marked done that the backend has not yet confirmed done. */
export type DoneIds = readonly string[]

const DONE_KEY = 'fs.done.v1'
const DONE_MAX = 50

export interface Reconciled {
  queue: Queue
  done: DoneIds
  resend: GlassesJsonMessage[]
}

export function markDone(done: DoneIds, taskId: string): DoneIds {
  return [...done.filter(id => id !== taskId), taskId].slice(-DONE_MAX)
}

/** Apply a `task.assigned` / `task.updated` from the backend on top of local state. */
export function applyBackendTask(queue: Queue, done: DoneIds, task: Task): Reconciled {
  const forget = done.filter(id => id !== task.id)
  if (task.state === 'done' || task.state === 'bounced') {
    return { queue: upsertTask(queue, task), done: forget, resend: [] }
  }
  if (done.includes(task.id)) {
    const resend: GlassesJsonMessage[] = []
    if (task.state === 'assigned') resend.push({ type: 'task.accept', taskId: task.id })
    resend.push({ type: 'task.done', taskId: task.id })
    return { queue: queue.filter(t => t.id !== task.id), done, resend }
  }
  const local = queue.find(t => t.id === task.id)
  if (local?.state === 'accepted' && task.state === 'assigned') {
    return {
      queue: upsertTask(queue, { ...task, state: 'accepted' }),
      done,
      resend: [{ type: 'task.accept', taskId: task.id }],
    }
  }
  return { queue: upsertTask(queue, task), done, resend: [] }
}

function isDoneIds(v: unknown): v is string[] {
  return Array.isArray(v) && v.every(id => typeof id === 'string')
}

export async function loadDone(bridge: EvenAppBridge): Promise<DoneIds> {
  try {
    const raw = await bridge.getLocalStorage(DONE_KEY)
    if (!raw) return []
    const v: unknown = JSON.parse(raw)
    return isDoneIds(v) ? v : []
  } catch (err) {
    log('loadDone failed', String(err))
    return []
  }
}

export async function saveDone(bridge: EvenAppBridge, done: DoneIds): Promise<void> {
  try {
    if (!(await bridge.setLocalStorage(DONE_KEY, JSON.stringify(done)))) log('saveDone returned false')
  } catch (err) {
    log('saveDone failed', String(err))
  }
}
