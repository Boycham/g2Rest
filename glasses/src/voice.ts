import type { GlassesJsonMessage, Task, VoiceIntent } from './contract'

// "verity <command>" from the relay -> what the glasses do. Task intents send the same frames
// as the gestures (the hub checks them against this socket's staff member) after a 3 s undo
// window; navigation intents act like the gesture at once.

export const UNDO_MS = 3000

export type VoiceAction =
  | { kind: 'gesture'; gesture: 'tap' | 'up' | 'down' | 'back' | 'clip' }
  | { kind: 'task'; send: GlassesJsonMessage }
  | { kind: 'refuse'; line: string }

export function voiceAction(intent: VoiceIntent, head: Task | undefined): VoiceAction {
  switch (intent) {
    case 'up':
    case 'down':
    case 'back':
    case 'clip':
      return { kind: 'gesture', gesture: intent }
    case 'confirm':
      return { kind: 'gesture', gesture: 'tap' }
    case 'accept':
      if (!head) return { kind: 'refuse', line: 'No task to accept' }
      if (head.state !== 'assigned') return { kind: 'refuse', line: 'Already accepted' }
      return { kind: 'task', send: { type: 'task.accept', taskId: head.id } }
    case 'decline':
      if (!head) return { kind: 'refuse', line: 'No task to decline' }
      if (head.state !== 'assigned') return { kind: 'refuse', line: "Can't decline: already accepted" }
      return { kind: 'task', send: { type: 'task.bounce', taskId: head.id } }
    case 'done':
      if (!head) return { kind: 'refuse', line: 'No task to finish' }
      return { kind: 'task', send: { type: 'task.done', taskId: head.id } }
  }
}
