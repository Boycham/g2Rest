import type { TaskHandoff } from './contract'

// Handoff (long hold or "verity handoff [name]"): a Confirm popup first, then task.handoff.
// Without a name the backend router picks anyone but the sender.

export function handoffPrompt(name?: string): string {
  return name ? `Confirm handoff to ${name}? (tap)` : 'Confirm handoff? (tap)'
}

export function handoffFrame(taskId: string, name?: string): TaskHandoff {
  return name ? { type: 'task.handoff', taskId, to: name } : { type: 'task.handoff', taskId }
}
