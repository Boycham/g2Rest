// The task board: Unassigned, Waiting for accept, Accepted, Done. When a task changes state
// its card flies to its new column (GSAP Flip): positions are recorded just before the store
// applies a backend message, then animated from there after React re-renders.
import { useEffect, useLayoutEffect, useRef } from 'react'
import { gsap } from 'gsap'
import { Flip } from 'gsap/Flip'
import { store } from './backend'
import type { View } from './App'
import { COLUMNS } from './model.js'
import { TaskCard, type CardView } from './ui'

gsap.registerPlugin(Flip)

const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches

export default function Board({ v, onOpen }: { v: View; onOpen: (t: string) => void }) {
  const root = useRef<HTMLElement>(null)
  const flip = useRef<Flip.FlipState | null>(null)

  useEffect(
    () =>
      store.onBeforeChange(() => {
        if (root.current) flip.current = Flip.getState(root.current.querySelectorAll('[data-flip-id]'))
      }),
    [],
  )

  useLayoutEffect(() => {
    const state = flip.current
    flip.current = null
    if (!state || !root.current || reduced()) return
    const lists = root.current.querySelectorAll<HTMLElement>('.col__list')
    lists.forEach((l) => l.classList.add('is-flipping'))
    Flip.from(state, {
      targets: root.current.querySelectorAll('[data-flip-id]'),
      duration: 0.5,
      ease: 'power2.inOut',
      zIndex: 5,
      onEnter: (els) => gsap.fromTo(els, { opacity: 0, scale: 0.92 }, { opacity: 1, scale: 1, duration: 0.3, ease: 'power2.out' }),
      onComplete: () => lists.forEach((l) => l.classList.remove('is-flipping')),
    })
  })

  return (
    <section className="board" ref={root} aria-label="Task board">
      {COLUMNS.map((col) => {
        const cards = v.cols[col.id as 'unassigned' | 'waiting' | 'accepted' | 'done'] as CardView[]
        const total = col.id === 'done' ? v.cols.doneTotal : cards.length
        return (
          <div key={col.id} className="panel col" aria-labelledby={`col-${col.id}`}>
            <div className="panel__row">
              <h2 id={`col-${col.id}`} className="col__h">
                {col.label}
              </h2>
              <span className="count" data-tone={col.tone}>
                {total}
              </span>
            </div>
            <div className="col__list">
              {cards.length ? (
                cards.map((c) => <TaskCard key={c.id} c={c} onOpen={onOpen} />)
              ) : (
                <div className="empty">{col.id === 'done' ? 'Nothing finished yet.' : 'None.'}</div>
              )}
            </div>
          </div>
        )
      })}
    </section>
  )
}
