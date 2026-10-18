import { getTextWidth } from '@evenrealities/pretext'
import { fit } from './card'
import type { Answer, OrderDraft } from './contract'

// The clip's "what the table said" block under the order: a separator, the summary, then a
// suggested reply per guest question (`?` when the menu can't answer). Display only: none of
// it is ever sent. Pure, measured with the G2 font, so it is tested.

export const SEPARATOR_LABEL = '── table said '
export const MAX_SUMMARY_LINES = 2
export const MAX_ANSWER_LINES = 2
const INDENT = '   '

/** Greedy word wrap by measured width; the last allowed line is truncated with an ellipsis. */
export function wrap(text: string, width: number, maxLines: number, indent = ''): string[] {
  const out: string[] = []
  let cur = ''
  const words = text.split(/\s+/).filter(Boolean)
  for (let i = 0; i < words.length; i++) {
    const lead = out.length ? indent : ''
    const next = cur ? `${cur} ${words[i]}` : lead + words[i]
    if (getTextWidth(next) <= width || !cur) {
      cur = next
      continue
    }
    if (out.length === maxLines - 1) {
      cur = `${cur} ${words.slice(i).join(' ')}`
      break
    }
    out.push(cur)
    cur = indent + words[i]
  }
  if (cur) out.push(fit(cur, width))
  return out.map(l => fit(l, width))
}

export function answerText(a: Answer): string {
  const seat = a.seat ? `s${a.seat} ` : ''
  if (a.known === false) return `? ${seat}asks ${a.q.replace(/\?+$/, '')}: ${a.a}`
  return `${seat}${a.q} → ${a.a}`
}

export function separator(width: number): string {
  let line = SEPARATOR_LABEL
  while (getTextWidth(`${line}─`) <= width) line += '─'
  return line
}

/** The lines under the order, or none when the clip had no summary and no answers. */
export function talkLines(d: OrderDraft | null, width: number): string[] {
  const summary = d?.summary?.trim() ?? ''
  const answers = d?.answers ?? []
  if (!summary && !answers.length) return []
  return [
    separator(width),
    ...(summary ? wrap(summary, width, MAX_SUMMARY_LINES) : []),
    ...answers.flatMap(a => wrap(answerText(a), width, MAX_ANSWER_LINES, INDENT)),
  ]
}
