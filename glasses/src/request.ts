import type { TableStatusSet, TaskRequest, VoiceRequest } from './contract'

/** How a status reads on the card: the model's `empty` is what a server calls free. */
function statusWord(r: VoiceRequest): string {
  if (r.status === 'empty') return r.note === 'paid' ? 'free (paid)' : 'free'
  if (r.status === 'seated' && r.vip) return 'VIP seated'
  if (r.status === 'waiting' && r.note) return `waiting ${r.note}`
  return r.status ?? ''
}

/** The confirm line: `Request: CHECK T2? tap`, `Request: RUN T4 bread? tap`, `T5 → free? tap`. */
export function requestLine(r: VoiceRequest): string {
  if (r.kind && (!r.status || r.status === 'check')) return `Request: ${r.kind} ${r.table}${r.note ? ` ${r.note}` : ''}? tap`
  return `${r.table} → ${statusWord(r)}? tap`
}

/** After the tap: `Sent: CHECK T2` / `T5 → free`. */
export function sentLine(r: VoiceRequest): string {
  return requestLine(r).replace(/^Request: /, 'Sent: ').replace(/\? tap$/, '')
}

/** A refused request ("no table 12"): nothing to confirm. */
export function refusedLine(r: VoiceRequest): string {
  return `Request: ${r.reason ?? 'refused'}`
}

/** The frame a tap sends: a status (with its task) or a task request. */
export function requestFrame(r: VoiceRequest): TaskRequest | TableStatusSet | null {
  if (r.reason) return null
  if (r.status) {
    return { type: 'table.status', table: r.table, status: r.status, ...(r.vip ? { vip: true } : {}), ...(r.note ? { note: r.note } : {}) }
  }
  if (!r.kind) return null
  return { type: 'task.request', table: r.table, kind: r.kind, ...(r.note ? { note: r.note } : {}) }
}
