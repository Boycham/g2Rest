// The scroll story: one fixed viewport, five scenes, and a tall page whose scroll position
// drives every layer. Lenis smooths the wheel, GSAP's ScrollTrigger turns the position into
// progress 0..1, and Lenis Snap settles on the nearest keyframe so each scroll steps to the
// next "page" of the story. Per-frame motion writes styles directly; React only re-renders
// when a scene or a keyframe step changes.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import Lenis from 'lenis'
import Snap from 'lenis/snap'
import Magnet from '../components/reactbits/Magnet'
import { links } from '../shared/links'
import { SCENES, STAGE, builtAt, local, sceneIndex, snapPoints, step } from './keyframes.js'
import { Ctx, asset, type Frame } from './frame'
import { Counter, Doors, Floor, Voice, Welcome } from './scenes'

gsap.registerPlugin(ScrollTrigger)

// Reduced motion: no smoothing, no snap, no crossfade; each scene holds the keyframe where
// it is fully built (builtAt), the same place the scene dots land.

function useReducedMotion() {
  const query = '(prefers-reduced-motion: reduce)'
  const [reduced, setReduced] = useState(() => matchMedia(query).matches)
  useEffect(() => {
    const mq = matchMedia(query)
    const on = () => setReduced(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return reduced
}

/** --cover / --fit / --fit-portrait: the stage's scale for the window. */
function useStageScale() {
  useLayoutEffect(() => {
    const set = () => {
      const w = innerWidth
      const h = innerHeight
      const root = document.documentElement.style
      root.setProperty('--cover', String(Math.max(w / STAGE.w, h / STAGE.h)))
      root.setProperty('--fit', String(Math.min(w / STAGE.w, h / STAGE.h)))
      root.setProperty('--fit-portrait', String(Math.min(w / 430, h / STAGE.h)))
    }
    set()
    addEventListener('resize', set)
    return () => removeEventListener('resize', set)
  }, [])
}

export default function Story() {
  const reduced = useReducedMotion()
  useStageScale()
  const frames = useRef(new Set<Frame>())
  const storyRef = useRef<HTMLDivElement>(null)
  const progressRef = useRef<HTMLDivElement>(null)
  const lenisRef = useRef<Lenis | null>(null)
  const [scene, setScene] = useState(0)
  const [steps, setSteps] = useState<number[]>([0, 0, 0, 0, 0])

  const register = useCallback((fn: Frame) => {
    frames.current.add(fn)
    return () => {
      frames.current.delete(fn)
    }
  }, [])

  const maxScroll = () => document.documentElement.scrollHeight - innerHeight
  const scrollToProgress = useCallback(
    (g: number) => {
      const y = g * maxScroll()
      if (lenisRef.current) lenisRef.current.scrollTo(y, { duration: 0.9 })
      else scrollTo({ top: y, behavior: reduced ? 'auto' : 'smooth' })
    },
    [reduced],
  )

  useEffect(() => {
    let lastKey = ''
    const update = (raw: number) => {
      let g = raw
      if (reduced) {
        const i = sceneIndex(raw)
        g = builtAt(i)
      }
      for (const fn of frames.current) fn(g)
      if (progressRef.current) progressRef.current.style.transform = `scaleX(${raw})`
      const i = sceneIndex(g)
      const next = SCENES.map((s) => step(local(g, s)))
      const key = `${i}:${next.join('')}`
      if (key !== lastKey) {
        lastKey = key
        setScene(i)
        setSteps(next)
      }
    }

    let lenis: Lenis | null = null
    let snap: Snap | null = null
    const raf = (time: number) => lenis?.raf(time * 1000)
    if (!reduced) {
      // Faster than the handoff (lerp 0.12, 1x wheel): the owner found the story too slow to scroll.
      lenis = new Lenis({ lerp: 0.2, wheelMultiplier: 2, touchMultiplier: 2, autoRaf: false, anchors: false })
      lenis.on('scroll', ScrollTrigger.update)
      gsap.ticker.add(raf)
      gsap.ticker.lagSmoothing(0)
      snap = new Snap(lenis, { type: 'proximity', duration: 0.6, debounce: 150, velocityThreshold: 1.2 })
    }
    lenisRef.current = lenis

    const removers: (() => void)[] = []
    const placeSnaps = () => {
      removers.splice(0).forEach((r) => r())
      if (!snap) return
      for (const g of snapPoints()) removers.push(snap.add(Math.round(g * maxScroll())))
    }

    const st = ScrollTrigger.create({
      trigger: storyRef.current,
      start: 'top top',
      end: 'bottom bottom',
      onUpdate: (self) => update(self.progress),
      onRefresh: (self) => {
        placeSnaps()
        update(self.progress)
      },
    })
    update(st.progress)
    placeSnaps()

    // Arrow keys and Page Up/Down step one keyframe, so the story reads like pages.
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && e.target.closest('input, select, textarea')) return
      const down = ['ArrowDown', 'PageDown', ' '].includes(e.key) && !e.shiftKey
      const up = ['ArrowUp', 'PageUp'].includes(e.key) || (e.key === ' ' && e.shiftKey)
      if (!down && !up) return
      e.preventDefault()
      const g = st.progress
      const points = reduced ? SCENES.map((_, i) => builtAt(i)) : snapPoints()
      const target = down ? points.find((p) => p > g + 0.002) : [...points].reverse().find((p) => p < g - 0.002)
      if (target !== undefined) scrollToProgress(target)
    }
    addEventListener('keydown', onKey)

    return () => {
      removeEventListener('keydown', onKey)
      removers.forEach((r) => r())
      st.kill()
      snap?.destroy()
      gsap.ticker.remove(raf)
      lenis?.destroy()
      lenisRef.current = null
    }
  }, [reduced, scrollToProgress])

  const fade = reduced ? 0 : 0.025
  return (
    <Ctx.Provider value={{ register, reduced, fade }}>
      <header className="nav">
        <a className="nav__logo" href={links.story} aria-label="Verity home">
          <img src={asset('logo-cream.png')} alt="Verity" />
        </a>
        <nav className="nav__links" aria-label="Pages">
          <a className="nav__link" href={links.story} aria-current="page">
            Market
          </a>
          <a className="nav__link" href={links.dashboard}>
            Dashboard
          </a>
          <a className="nav__link" href={links.kitchen}>
            Kitchen
          </a>
        </nav>
        <Magnet padding={40} magnetStrength={4} disabled={reduced}>
          <a className="nav__cta" href={links.dashboard}>
            Open dashboard
          </a>
        </Magnet>
        <div className="nav__progress" ref={progressRef} />
      </header>

      <ol className="dots" aria-label="Scenes">
        {SCENES.map((s, i) => (
          <li key={s.id}>
            <button
              type="button"
              className="dot"
              aria-current={scene === i ? 'step' : undefined}
              onClick={() => scrollToProgress(builtAt(i))}
            >
              <span className="dot__label">{s.label}</span>
              <span className="dot__mark" />
            </button>
          </li>
        ))}
      </ol>

      <main className="viewport">
        {[Welcome, Counter, Voice, Doors, Floor].map((Scene, i) => (
          <Scene key={SCENES[i].id} index={i} active={scene === i} past={scene > i} step={steps[i]} />
        ))}
      </main>
      <div className="story" ref={storyRef} aria-hidden="true" />
    </Ctx.Provider>
  )
}
