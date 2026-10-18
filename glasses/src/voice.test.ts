import { describe, expect, it } from 'vitest'
import { makeTask } from './fixtures.test-helpers'
import { voiceAction } from './voice'

describe('voiceAction', () => {
  const assigned = makeTask({ id: 't1' })
  const accepted = { ...assigned, state: 'accepted' as const }

  it('sends the same frames as the gestures for task intents', () => {
    expect(voiceAction('accept', assigned)).toEqual({ kind: 'task', send: { type: 'task.accept', taskId: 't1' } })
    expect(voiceAction('decline', assigned)).toEqual({ kind: 'task', send: { type: 'task.bounce', taskId: 't1' } })
    expect(voiceAction('done', accepted)).toEqual({ kind: 'task', send: { type: 'task.done', taskId: 't1' } })
  })

  it('says why instead of failing silently', () => {
    expect(voiceAction('decline', accepted)).toEqual({ kind: 'refuse', line: "Can't decline: already accepted" })
    expect(voiceAction('accept', undefined).kind).toBe('refuse')
  })

  it('maps navigation to gestures, confirm to a tap', () => {
    expect(voiceAction('confirm', assigned)).toEqual({ kind: 'gesture', gesture: 'tap' })
    expect(voiceAction('clip', undefined)).toEqual({ kind: 'gesture', gesture: 'clip' })
  })
})
