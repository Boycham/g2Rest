import type { GlassesJsonMessage, Task, VoiceIntent } from './contract'

// "verity <command>" from the relay -> what the glasses do. Task intents send the same frames
// as the gestures; the backend decides and answers task.updated or task.rejected (its reason
// goes on the card as is). Handoff opens a Confirm popup first.

export type VoiceGesture = 'up' | 'down' | 'back' | 'clip' | 'menu' | 'queue'

export type VoiceAction =
  | { kind: 'gesture'; gesture: VoiceGesture }
  | { kind: 'confirm' }
  | { kind: 'nevermind' }
  | { kind: 'task'; send: GlassesJsonMessage }
  | { kind: 'handoff'; taskId: string; name?: string }
  | { kind: 'refuse'; line: string }

export function voiceAction(intent: VoiceIntent, head: Task | undefined, name?: string): VoiceAction {
  switch (intent) {
    case 'up':
    case 'down':
    case 'back':
    case 'clip':
    case 'menu':
    case 'queue':
      return { kind: 'gesture', gesture: intent }
    case 'confirm':
    case 'nevermind':
      return { kind: intent }
    case 'revert':
      return { kind: 'task', send: { type: 'task.revert' } }
    case 'accept':
      if (!head) return { kind: 'refuse', line: 'No task to accept' }
      return { kind: 'task', send: { type: 'task.accept', taskId: head.id } }
    case 'decline':
      if (!head) return { kind: 'refuse', line: 'No task to decline' }
      return { kind: 'task', send: { type: 'task.bounce', taskId: head.id } }
    case 'done':
      if (!head) return { kind: 'refuse', line: 'No task to finish' }
      return { kind: 'task', send: { type: 'task.done', taskId: head.id } }
    case 'handoff':
      if (!head) return { kind: 'refuse', line: 'No task to hand off' }
      return name ? { kind: 'handoff', taskId: head.id, name } : { kind: 'handoff', taskId: head.id }
  }
}

/** `Didn't get: <words>`, plus why when Gemini wasn't reachable. */
export function didntGet(words: string, reason?: string): string {
  const shown = words.length > 30 ? `${words.slice(0, 29)}…` : words
  return reason ? `Didn't get: ${shown} (${reason})` : `Didn't get: ${shown}`
}
