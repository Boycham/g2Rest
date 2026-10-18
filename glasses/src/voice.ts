import type { GlassesJsonMessage, Task, TaskRejected, VoiceCommand, VoiceIntent } from './contract'

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
    case 'table':
      // The relay already bound the draft (or refused); the glasses only say what happened.
      return { kind: 'refuse', line: 'say verity table and a number' }
  }
}

const REJECTED_VERB: Record<TaskRejected['action'], string> = {
  accept: 'accept',
  done: 'finish',
  bounce: 'decline',
  handoff: 'hand off',
  revert: 'revert',
}

/** The card line for a task.rejected: the action in plain words, then the backend's reason. */
export function rejectionLine(msg: Pick<TaskRejected, 'action' | 'reason'>, task?: Task): string {
  if (msg.action === 'bounce' && (task?.state === 'accepted' || /accepted/i.test(msg.reason)))
    return "Can't decline: already accepted"
  return `Can't ${REJECTED_VERB[msg.action]}: ${msg.reason}`
}

/** "verity table 4": `Table T3 → T4`, `Heard: table T4`, or the relay's reason. */
export function tableLine(cmd: Pick<VoiceCommand, 'table' | 'was' | 'reason'>): string {
  if (cmd.reason) return cmd.table ? `${cmd.table}: ${cmd.reason}` : cmd.reason
  if (cmd.was) return `Table ${cmd.was} → ${cmd.table}`
  return `Heard: table ${cmd.table ?? '?'}`
}

/** `Didn't get: <words>`, plus why when Gemini wasn't reachable. */
export function didntGet(words: string, reason?: string): string {
  const shown = words.length > 30 ? `${words.slice(0, 29)}…` : words
  return reason ? `Didn't get: ${shown} (${reason})` : `Didn't get: ${shown}`
}
