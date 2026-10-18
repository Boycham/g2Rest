import type { Task } from './contract'

export function makeTask(over: Partial<Task> = {}): Task {
  return {
    id: 't1',
    kind: 'RUN',
    table: 'T12',
    items: [{ qty: 2, dish: 'halibut', seats: [1, 3] }],
    allergies: [],
    notes: [],
    state: 'assigned',
    ...over,
  }
}
