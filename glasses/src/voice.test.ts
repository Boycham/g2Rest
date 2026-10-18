import { describe, expect, it } from 'vitest'
import { makeTask } from './fixtures.test-helpers'
import { handoffFrame, handoffPrompt } from './handoff'
import { didntGet, rejectionLine, voiceAction } from './voice'

describe('voiceAction', () => {
  const assigned = makeTask({ id: 't1' })
  const accepted = { ...assigned, state: 'accepted' as const }

  it('sends the same frames as the gestures and lets the backend refuse', () => {
    expect(voiceAction('accept', assigned)).toEqual({ kind: 'task', send: { type: 'task.accept', taskId: 't1' } })
    expect(voiceAction('decline', accepted)).toEqual({ kind: 'task', send: { type: 'task.bounce', taskId: 't1' } })
    expect(voiceAction('done', accepted)).toEqual({ kind: 'task', send: { type: 'task.done', taskId: 't1' } })
    expect(voiceAction('revert', undefined)).toEqual({ kind: 'task', send: { type: 'task.revert' } })
  })

  it('says why when there is no task at all', () => {
    expect(voiceAction('accept', undefined)).toEqual({ kind: 'refuse', line: 'No task to accept' })
    expect(voiceAction('handoff', undefined)).toEqual({ kind: 'refuse', line: 'No task to hand off' })
  })

  it('maps navigation to gestures and keeps confirm and nevermind for the HUD', () => {
    expect(voiceAction('clip', undefined)).toEqual({ kind: 'gesture', gesture: 'clip' })
    expect(voiceAction('menu', undefined)).toEqual({ kind: 'gesture', gesture: 'menu' })
    expect(voiceAction('queue', undefined)).toEqual({ kind: 'gesture', gesture: 'queue' })
    expect(voiceAction('confirm', assigned)).toEqual({ kind: 'confirm' })
    expect(voiceAction('nevermind', assigned)).toEqual({ kind: 'nevermind' })
  })

  it('opens a handoff popup for the head task, with the name if one was said', () => {
    expect(voiceAction('handoff', accepted, 'Ben')).toEqual({ kind: 'handoff', taskId: 't1', name: 'Ben' })
    expect(voiceAction('handoff', assigned)).toEqual({ kind: 'handoff', taskId: 't1' })
  })
})

describe('handoff', () => {
  it('asks first, then sends task.handoff with an optional to', () => {
    expect(handoffPrompt('Ben')).toBe('Confirm handoff to Ben? (tap)')
    expect(handoffFrame('t1', 'Ben')).toEqual({ type: 'task.handoff', taskId: 't1', to: 'Ben' })
    expect(handoffFrame('t1')).toEqual({ type: 'task.handoff', taskId: 't1' })
  })
})

describe('didntGet', () => {
  it('shows the words and the reason Gemini could not help', () => {
    expect(didntGet('sing louder')).toBe("Didn't get: sing louder")
    expect(didntGet('sing', 'timeout')).toBe("Didn't get: sing (timeout)")
  })
})

describe('rejectionLine', () => {
  const accepted = { ...makeTask({ id: 't1' }), state: 'accepted' as const }

  it('says exactly why a decline of an accepted task was refused', () => {
    expect(rejectionLine({ action: 'bounce', reason: 'task-t1 is accepted, cannot bounce' })).toBe(
      "Can't decline: already accepted",
    )
    expect(rejectionLine({ action: 'bounce', reason: 'not yours' }, accepted)).toBe("Can't decline: already accepted")
  })

  it('names the other actions in plain words and keeps the backend reason', () => {
    expect(rejectionLine({ action: 'revert', reason: 'nothing to revert' })).toBe("Can't revert: nothing to revert")
    expect(rejectionLine({ action: 'handoff', reason: 'Ben already accepted it' })).toBe(
      "Can't hand off: Ben already accepted it",
    )
    expect(rejectionLine({ action: 'bounce', reason: 'not your task' })).toBe("Can't decline: not your task")
    expect(rejectionLine({ action: 'done', reason: 'not accepted' })).toBe("Can't finish: not accepted")
  })
})
