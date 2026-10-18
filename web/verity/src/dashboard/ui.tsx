// Small pieces the dashboard repeats: the countdown ring, the task card, chips and icons.
import type { ReactNode } from 'react'
import { clock, tableNo } from './model.js'

export type CardView = {
  id: string
  kind: string
  table: string
  title: string
  subtitle: string
  variant: 'unassigned' | 'waiting' | 'escalated' | 'bounced' | 'accepted' | 'done' | 'reverted'
  ring: { left: number; total: number } | null
  assignee: string
  name: string
}

const R = 20
const C = 2 * Math.PI * R

/** The 52px countdown ring: drains linearly over the escalation window, red once over. */
export function Ring({ left, total, over }: { left: number; total: number; over: boolean }) {
  const frac = Math.max(0, Math.min(1, left / total))
  const label = left >= 0 ? clock(left) : clock(-left)
  return (
    <div className="ring" data-over={over} title={left >= 0 ? `${label} left to accept` : `${label} over the limit`}>
      <svg width="52" height="52" viewBox="0 0 52 52" aria-hidden="true">
        <circle cx="26" cy="26" r={R} className="ring__track" />
        <circle
          cx="26"
          cy="26"
          r={R}
          className="ring__arc"
          strokeDasharray={C}
          strokeDashoffset={over ? 0 : C * (1 - frac)}
          transform="rotate(-90 26 26)"
        />
      </svg>
      <span className="ring__text">{label}</span>
    </div>
  )
}

export function DoneCheck() {
  return (
    <svg width="28" height="28" viewBox="0 0 64 64" aria-label="done">
      <path d="M33 7 Q57 8 57.5 32 Q58 57 32 57.5 Q7 57 7 32 Q7 7 33 7 Z" fill="#93BF6B" />
      <path d="M19 33 L28 42 L46 22" fill="none" stroke="#1A1917" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function TableChip({ table }: { table: string }) {
  return <span className="chip-table">T{tableNo(table)}</span>
}

/** A task card in one of the seven design states. */
export function TaskCard({ c, onOpen }: { c: CardView; onOpen?: (table: string) => void }) {
  return (
    <button
      type="button"
      className="card"
      data-variant={c.variant}
      data-flip-id={c.id}
      onClick={() => onOpen?.(c.table)}
      aria-label={`${c.title}, table ${c.table}. ${c.subtitle}`}
    >
      <span className="card__text">
        <span className="card__title">{c.title}</span>
        <span className="card__sub">{c.subtitle}</span>
      </span>
      <span className="card__side">
        {c.ring && <Ring left={c.ring.left} total={c.ring.total} over={c.variant === 'escalated' && c.ring.left < 0} />}
        {c.variant === 'done' && <DoneCheck />}
        <TableChip table={c.table} />
      </span>
    </button>
  )
}

export function StatusChip({ tone, children }: { tone: 'leaf' | 'red' | 'bone'; children: ReactNode }) {
  return (
    <span className="status-chip" data-tone={tone}>
      <span className="status-chip__dot" />
      {children}
    </span>
  )
}

export const icons = {
  staff: (
    <svg viewBox="0 0 64 64" aria-hidden="true">
      <path d="M32 8 Q43 8 42.5 20 Q42 31 32 31.5 Q22 31 21.5 20 Q21 8 32 8 Z" fill="#F2EFE6" />
      <path d="M9 57 Q9 37 32 36.5 Q55 37 55 57 Z" fill="#F2EFE6" />
      <path d="M35 42 L45 42.5 L44.5 48 L34.5 47.5 Z" fill="#E4DCC8" />
    </svg>
  ),
  log: (
    <svg viewBox="0 0 64 64" aria-hidden="true">
      <path
        d="M10 32 L22 32.5 Q30 32.5 35 25 L47 13.5 M22 32.5 Q30 32.5 35 40 L47 51"
        fill="none"
        stroke="#F2EFE6"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M41 7 L57 7.5 L56.5 23 Z M41 57 L56.5 57.5 L57 41 Z" fill="#F2EFE6" />
      <circle cx="8" cy="32" r="4.6" fill="#E4DCC8" />
    </svg>
  ),
  table: (
    <svg viewBox="0 0 64 64" aria-hidden="true">
      <path d="M6 25 Q32 19 58 25 L56 31.5 Q32 37 8 31.5 Z" fill="#F2EFE6" />
      <path d="M28 33 L36 33 L37 53 L27 53 Z" fill="#F2EFE6" />
      <path d="M15 53.5 Q32 50.5 49 53.5 L48.5 58 Q32 56 15.5 58 Z" fill="#F2EFE6" />
      <path d="M25 18.5 L39 18.5 Q38 24.5 32 25 Q26 24.5 25 18.5 Z" fill="#E4DCC8" />
    </svg>
  ),
  close: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  ),
}
