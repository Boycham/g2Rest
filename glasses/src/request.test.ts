import { describe, expect, it } from 'vitest'
import type { VoiceRequest } from './contract'
import { parseBackendMessage } from './parse'
import { refusedLine, requestFrame, requestLine, sentLine } from './request'

const req = (r: Partial<VoiceRequest>): VoiceRequest => ({ type: 'voice.request', table: 'T2', source: 'clip', ...r })

describe('spoken requests', () => {
  it('shows a confirm line for each request kind', () => {
    expect(requestLine(req({ kind: 'CHECK', status: 'check' }))).toBe('Request: CHECK T2? tap')
    expect(requestLine(req({ table: 'T4', kind: 'RUN', note: 'bread' }))).toBe('Request: RUN T4 bread? tap')
    expect(requestLine(req({ table: 'T3', kind: 'CLEAR' }))).toBe('Request: CLEAR T3? tap')
    expect(requestLine(req({ table: 'T5', kind: 'ORDER' }))).toBe('Request: ORDER T5? tap')
  })

  it('shows every table status as T → status', () => {
    expect(requestLine(req({ status: 'empty', note: 'paid' }))).toBe('T2 → free (paid)? tap')
    expect(requestLine(req({ table: 'T5', status: 'empty' }))).toBe('T5 → free? tap')
    expect(requestLine(req({ status: 'seated' }))).toBe('T2 → seated? tap')
    expect(requestLine(req({ status: 'seated', vip: true }))).toBe('T2 → VIP seated? tap')
    expect(requestLine(req({ status: 'ordered' }))).toBe('T2 → ordered? tap')
    expect(requestLine(req({ status: 'waiting', note: 'on mains' }))).toBe('T2 → waiting on mains? tap')
    expect(requestLine(req({ status: 'eating' }))).toBe('T2 → eating? tap')
    expect(sentLine(req({ kind: 'CHECK', status: 'check' }))).toBe('Sent: CHECK T2')
    expect(sentLine(req({ status: 'eating' }))).toBe('T2 → eating')
  })

  it('a tap sends table.status for a status and task.request for a task', () => {
    expect(requestFrame(req({ kind: 'CHECK', status: 'check' }))).toEqual({ type: 'table.status', table: 'T2', status: 'check' })
    expect(requestFrame(req({ status: 'seated', vip: true }))).toEqual({ type: 'table.status', table: 'T2', status: 'seated', vip: true })
    expect(requestFrame(req({ table: 'T4', kind: 'RUN', note: 'bread' }))).toEqual({ type: 'task.request', table: 'T4', kind: 'RUN', note: 'bread' })
    expect(requestFrame(req({ kind: 'CHECK', reason: 'no table 12' }))).toBeNull()
    expect(refusedLine(req({ table: 'T12', reason: 'no table 12' }))).toBe('Request: no table 12')
  })

  it('parses voice.request and rejects malformed ones', () => {
    const ok = '{"type":"voice.request","table":"T2","kind":"CHECK","status":"check","source":"voice"}'
    expect(parseBackendMessage(ok)).toMatchObject({ kind: 'CHECK', table: 'T2' })
    expect(parseBackendMessage('{"type":"voice.request","table":"T12","kind":"CHECK","source":"voice","reason":"no table 12"}')).not.toBeNull()
    expect(parseBackendMessage('{"type":"voice.request","table":"T2","source":"voice"}')).toBeNull()
    expect(parseBackendMessage('{"type":"voice.request","table":"T2","kind":"FIRE","source":"voice"}')).toBeNull()
    expect(parseBackendMessage('{"type":"voice.request","table":"T2","status":"paid","source":"voice"}')).toBeNull()
    expect(parseBackendMessage('{"type":"voice.request","table":"T2","kind":"RUN","source":"phone"}')).toBeNull()
    expect(parseBackendMessage('{"type":"task.rejected","taskId":null,"action":"status","reason":"no table T99"}')).not.toBeNull()
  })
})
