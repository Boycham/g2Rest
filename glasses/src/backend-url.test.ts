import { describe, expect, it } from 'vitest'
import { backendUrl, redactToken } from './backend-url'

describe('backendUrl', () => {
  it('adds token, role and the default staff for each role', () => {
    expect(backendUrl('ws://localhost:8787/ws', 'server', 'dev')).toBe('ws://localhost:8787/ws?token=dev&role=server&staff=s1')
    expect(backendUrl('ws://localhost:8787/ws', 'manager', 'dev')).toBe('ws://localhost:8787/ws?token=dev&role=manager&staff=m1')
  })

  it('leaves the token out when there is none (open dev backend, fake backend)', () => {
    expect(backendUrl('ws://localhost:8787/ws', 'server')).toBe('ws://localhost:8787/ws?role=server&staff=s1')
  })

  it('uses VITE_FS_STAFF for the server only', () => {
    expect(backendUrl('ws://h/ws', 'server', '', 's2')).toContain('staff=s2')
    expect(backendUrl('ws://h/ws', 'manager', '', 's2')).toContain('staff=m1')
  })

  it('keeps a token already on the base URL', () => {
    expect(backendUrl('wss://h/ws?token=abc', 'server', 'dev')).toBe('wss://h/ws?token=abc&role=server&staff=s1')
  })

  it('lets the role picker win over role and staff baked into the base URL (real-G2 bug)', () => {
    const base = 'ws://100.64.0.1:8787/ws?role=server&staff=s1'
    expect(backendUrl(base, 'manager', 'dev')).toBe('ws://100.64.0.1:8787/ws?role=manager&staff=m1&token=dev')
    expect(backendUrl(base, 'server', '', 's2')).toContain('role=server&staff=s2')
  })

  it('redacts the token for display', () => {
    expect(redactToken('ws://h/ws?token=secret&role=server')).not.toContain('secret')
  })
})
