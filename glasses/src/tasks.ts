import type { GlassesJsonMessage, Task, TaskState } from './contract'

// Glasses-side view of the server's queue. The backend owns task state; this mirrors
// it and applies the wearer's taps optimistically so the card reacts instantly.

export type Queue = readonly Task[]

export function isOpen(state: TaskState): boolean {
  return state === 'assigned' || state === 'accepted'
}

/** `task.assigned` and `task.updated` both carry the full task. */
export function upsertTask(queue: Queue, task: Task): Queue {
  const i = queue.findIndex(t => t.id === task.id)
  if (!isOpen(task.state)) return i === -1 ? queue : queue.filter(t => t.id !== task.id)
  if (i === -1) return [...queue, task]
  const next = queue.slice()
  next[i] = task
  return next
}

export interface TapResult {
  queue: Queue
  send: GlassesJsonMessage | null
}

/** Tap = accept the current card; tap again = done, which reveals the next card. */
export function tap(queue: Queue): TapResult {
  const head = queue[0]
  if (!head) return { queue, send: null }
  if (head.state === 'assigned') {
    return {
      queue: [{ ...head, state: 'accepted' }, ...queue.slice(1)],
      send: { type: 'task.accept', taskId: head.id },
    }
  }
  return { queue: queue.slice(1), send: { type: 'task.done', taskId: head.id } }
}
