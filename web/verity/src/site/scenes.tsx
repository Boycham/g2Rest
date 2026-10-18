// The five scenes of the scroll story, laid out as the Paper artboards draw them.
// Continuous motion (camera moves, doors, fades) runs in useFrame; discrete states
// (card and panel states, text swaps) come from `step`, the nearest keyframe.
import { useRef, type CSSProperties, type ReactNode } from 'react'
import CountUp from '../components/reactbits/CountUp'
import Magnet from '../components/reactbits/Magnet'
import ShinyText from '../components/reactbits/ShinyText'
import SplitText from '../components/reactbits/SplitText'
import { links } from '../shared/links'
import { asset, useFrame, useSceneRoot, useStory } from './frame'
import {
  PINS,
  PLATE0,
  counterLayers,
  doorsLayers,
  floorLayers,
  voiceLayers,
  welcomeLayers,
} from './keyframes.js'

type SceneProps = { index: number; active: boolean; past: boolean; step: number }
type Rect = number[]

/** Move a layer drawn at KF0 width `baseW` to `rect`, as translate + uniform scale. */
function place(el: HTMLElement | null, rect: Rect, baseW: number) {
  if (!el) return
  const [l, t, w] = rect
  el.style.transform = `translate3d(${l.toFixed(2)}px, ${t.toFixed(2)}px, 0) scale(${(w / baseW).toFixed(5)})`
}

function show(el: HTMLElement | null, opacity: number) {
  if (!el) return
  el.style.opacity = opacity.toFixed(3)
  el.style.visibility = opacity > 0.001 ? 'visible' : 'hidden'
}

/**
 * A scene heading. Before its scene it waits hidden, while its scene is live it animates in
 * word by word with React Bits SplitText, and once passed it stays as plain text so the
 * outgoing crossfade doesn't flicker.
 */
function Heading({
  text,
  className,
  live,
  past,
  tag = 'h2',
  align = 'left',
}: {
  text: string
  className: string
  live: boolean
  past: boolean
  tag?: 'h1' | 'h2'
  align?: 'left' | 'center'
}) {
  const { reduced } = useStory()
  if (live && !reduced) {
    return (
      <SplitText
        key="live"
        tag={tag}
        className={className}
        text={text}
        splitType="words"
        effect="rise"
        trigger="load"
        delay={45}
        duration={0.9}
        textAlign={align}
        mask
      />
    )
  }
  const Tag = tag
  return (
    <Tag className={className} style={{ textAlign: align, opacity: live || past ? 1 : 0 }}>
      {text}
    </Tag>
  )
}

function Cue({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div className="cue" style={style}>
      <span>
        <ShinyText color="#c2bcae" shineColor="#f2efe6" speed={2.6}>
          {children}
        </ShinyText>
        <span className="cue__arrow" aria-hidden="true">
          ↓
        </span>
      </span>
    </div>
  )
}

// ---------- S01 welcome: the shopfront, pushed in toward the door ----------

export function Welcome({ index, active, past }: SceneProps) {
  const root = useSceneRoot(index)
  const photo = useRef<HTMLDivElement>(null)
  useFrame((g) => place(photo.current, welcomeLayers(root.local(g)).photo, PLATE0[2]))
  return (
    <section ref={root.ref} className="scene welcome" aria-label="Welcome">
      <div className="cover">
        <div className="plate" ref={photo}>
          <img src={asset('shopfront.jpg')} alt="" />
          {/* SIGN_LOGO rides the photo's camera, so it lives inside the plate */}
          <img
            src={asset('logo-cream.png')}
            alt=""
            style={{ position: 'absolute', left: 625 - PLATE0[0], top: 112 - PLATE0[1], width: 180, height: 79 }}
          />
        </div>
        <div
          className="scrim"
          style={{ left: 0, top: 420, width: 1440, height: 480, background: 'linear-gradient(180deg, #0b0b0a00, #0b0b0ad1)' }}
        />
      </div>
      <div className="fit">
        <Heading
          tag="h1"
          className="title tagline"
          text="Restaurant coordination made better, faster, and quieter."
          live={active}
          past={past}
          align="center"
        />
        <Cue>Scroll to explore</Cue>
      </div>
    </section>
  )
}

// ---------- S02 counter: a task card through new, accepted, done ----------

const CARD = [
  { badge: 'NEW', tone: 'bone', border: 'bone', hint: 'Tap the temple once to accept.' },
  { badge: 'NEW', tone: 'bone', border: 'bone', hint: 'Tap the temple once to accept.' },
  { badge: 'ACCEPTED', tone: 'leaf-fill', border: 'leaf', hint: 'Tap twice when the plates are out.' },
  { badge: 'DONE', tone: 'leaf', border: 'leaf', hint: 'Manager sees it clear on the dashboard.' },
  { badge: 'DONE', tone: 'leaf', border: 'leaf', hint: 'Manager sees it clear on the dashboard.' },
]
const GESTURE = ['TAP ×1 · ACCEPT', 'TAP ×1 · ACCEPT', 'TAP ×2 · DONE', 'CLEARED', 'NEXT TASK']

function CardMono({ step }: { step: number }) {
  if (step <= 1)
    return (
      <>
        0:
        <CountUp key={`c${step}`} from={60} to={42} direction="down" duration={1.1} trigger="load" /> to accept
      </>
    )
  if (step === 2) return <>Accepted 0:42 after sending</>
  return <>Done in 02:48</>
}

export function Counter({ index, active, past, step }: SceneProps) {
  const root = useSceneRoot(index)
  const photo = useRef<HTMLDivElement>(null)
  const card = useRef<HTMLDivElement>(null)
  const next = useRef<HTMLDivElement>(null)
  const gesture = useRef<HTMLDivElement>(null)
  useFrame((g) => {
    const l = counterLayers(root.local(g))
    place(photo.current, l.photo, PLATE0[2])
    show(card.current, l.card)
    show(next.current, l.next)
    show(gesture.current, l.gesture)
  })
  const c = CARD[step]
  return (
    <section ref={root.ref} className="scene counter" aria-label="Tasks on the glasses">
      <div className="cover">
        <div className="plate" ref={photo}>
          <img src={asset('counter.jpg')} alt="" />
        </div>
        <div className="scrim scrim--left" />
      </div>
      <div className="fit">
        <Heading className="title" text="Orders find the right pair of hands." live={active} past={past} />
        <p className="body">
          The task lands on the server's glasses. One tap accepts it. Two taps finish it. Nobody shouts across the
          pass.
        </p>
        <div className="g2 main" ref={card} data-tone={c.border} aria-label="Task card on the glasses">
          <div className="g2__label">TASK</div>
          <div className="badge swap" key={`b${c.badge}`} data-tone={c.tone}>
            {c.badge}
          </div>
          <div className="g2__table">Table 04</div>
          <div className="g2__what">Pick up food</div>
          <div className="g2__rule" />
          <div className="g2__mono swap" key={`m${Math.min(step, 3)}${step <= 1 ? 'n' : ''}`}>
            <CardMono step={step} />
          </div>
          <div className="g2__hint swap" key={`h${c.hint}`}>
            {c.hint}
          </div>
        </div>
        <div className="g2 next" ref={next} data-tone="bone" aria-label="The next task">
          <div className="g2__label">TASK</div>
          <div className="badge" data-tone="bone">
            NEW
          </div>
          <div className="g2__table">Table 07</div>
          <div className="g2__what">Clear table</div>
          <div className="g2__rule" />
          <div className="g2__mono">0:60 to accept</div>
          <div className="g2__hint">Tap the temple once to accept.</div>
        </div>
        <div className="gesture" ref={gesture}>
          <span className="tap-ring" aria-hidden="true" />
          <span className="swap" key={GESTURE[step]}>
            {GESTURE[step]}
          </span>
        </div>
      </div>
    </section>
  )
}

// ---------- S03 voice: speak, structure, confirm, sent ----------

const HEARD = 'Table four, two tonkotsu, one barley tea, and no onions on the…'
const FULL = 'Table four, two tonkotsu, one barley tea, and no onions on the first bowl.'
const VOICE = [
  { tag: 'READY', tone: 'bone', live: false, text: 'Swipe back to clip the last minute.', done: false, slip: false, pill: 'Waiting for an order', pillTone: '' },
  { tag: 'LISTENING', tone: 'red', live: true, text: HEARD, done: false, slip: false, pill: 'Listening…', pillTone: '' },
  { tag: 'STRUCTURING', tone: 'bone', live: false, text: HEARD, done: false, slip: true, pill: 'Building the ticket…', pillTone: '' },
  { tag: 'CONFIRM', tone: 'cream', live: false, text: FULL, done: true, slip: true, pill: 'Tap once to confirm', pillTone: 'cream' },
  { tag: 'SENT', tone: 'leaf', live: false, text: FULL, done: true, slip: true, pill: 'Sent to Ben · 0:60 to accept', pillTone: 'leaf' },
]
const BARS = [10, 22, 38, 56, 30, 66, 44, 78, 52, 70, 34, 60, 26, 40, 16, 8]

function MicIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <rect x="9" y="3" width="6" height="12" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" strokeLinecap="round" />
    </svg>
  )
}

export function Voice({ index, active, past, step }: SceneProps) {
  const root = useSceneRoot(index)
  const photo = useRef<HTMLDivElement>(null)
  useFrame((g) => place(photo.current, voiceLayers(root.local(g)).photo, PLATE0[2]))
  const v = VOICE[step]
  return (
    <section ref={root.ref} className="scene voice" aria-label="Voice orders">
      <div className="cover">
        <div className="plate" ref={photo}>
          <img src={asset('table.jpg')} alt="" />
        </div>
        <div className="scrim scrim--left" />
      </div>
      <div className="fit">
        <Heading className="title" text="Speak. Confirm. Serve." live={active} past={past} />
        <p className="body">
          Say the order out loud. Verity turns it into a clean ticket, asks for one tap to confirm, then sends it to the
          right server.
        </p>
        <div className="panel" aria-label="Voice order panel">
          <div className="mic" data-live={v.live}>
            <MicIcon />
          </div>
          <div className="tag swap" key={v.tag} data-tone={v.tone}>
            {v.tag}
          </div>
          <p className="transcript swap" key={`t${v.text}${v.done}`} data-done={v.done}>
            {v.text}
          </p>
          <div className="wave" data-live={v.live} aria-hidden="true">
            {BARS.map((hgt, i) => (
              <span
                key={i}
                style={{ left: i * 16, height: v.live ? hgt : 6, animationDelay: `${(i % 5) * -120}ms` }}
              />
            ))}
          </div>
          <div className="slip" data-shown={v.slip}>
            <div className="slip__head">TICKET · TABLE 04</div>
            <div className="slip__line">2× Tonkotsu ramen</div>
            <div className="slip__line">1× Barley tea</div>
            <div className="slip__note">Note: no onions</div>
            <div className="slip__rule" />
            <div className="slip__route">Route to: Ben (auto)</div>
          </div>
          <div className="confirm swap" key={v.pill} data-tone={v.pillTone}>
            {v.pill}
          </div>
        </div>
      </div>
    </section>
  )
}

// ---------- S04 doors: the shopfront doors part onto the dining room ----------

export function Doors({ index, active, past, step }: SceneProps) {
  const root = useSceneRoot(index)
  const interior = useRef<HTMLDivElement>(null)
  const shade = useRef<HTMLDivElement>(null)
  const left = useRef<HTMLDivElement>(null)
  const right = useRef<HTMLDivElement>(null)
  const scrim = useRef<HTMLDivElement>(null)
  const copy = useRef<HTMLDivElement>(null)
  const cue = useRef<HTMLDivElement>(null)
  useFrame((g) => {
    const l = doorsLayers(root.local(g))
    place(interior.current, l.interior, PLATE0[2])
    show(shade.current, l.shade)
    if (left.current) left.current.style.transform = `translate3d(${l.left.toFixed(1)}px,0,0)`
    if (right.current) right.current.style.transform = `translate3d(${l.right.toFixed(1)}px,0,0)`
    show(scrim.current, l.copy)
    show(copy.current, l.copy)
    show(cue.current, 1 - l.copy)
  })
  const copyLive = active && step >= 3
  return (
    <section ref={root.ref} className="scene doors" aria-label="Inside the restaurant">
      <div className="cover">
        <div className="plate" ref={interior}>
          <img src={asset('interior.jpg')} alt="" />
        </div>
        <div ref={shade} className="scrim" style={{ left: 0, top: 76, width: 1440, height: 824, background: '#0b0b0a' }} />
        <div className="door" ref={left} style={{ left: 0 }}>
          <img src={asset('doors.jpg')} alt="" style={{ left: PLATE0[0] }} />
        </div>
        <div className="door" ref={right} style={{ left: 0 }}>
          <img src={asset('doors.jpg')} alt="" style={{ left: PLATE0[0] - 720 }} />
        </div>
        <div ref={scrim} className="scrim scrim--left" />
      </div>
      <div className="fit">
        <div ref={copy}>
          <Heading className="title" text="A restaurant that talks to itself." live={copyLive} past={past} />
          <p className="body">
            Doors, tables, pass and floor share one live picture. Every person sees only what is theirs to do.
          </p>
        </div>
        <div ref={cue}>
          <Cue>
            <span className="swap" key={step === 0 ? 'open' : 'keep'}>
              {step === 0 ? 'Scroll to open' : 'Keep scrolling'}
            </span>
          </Cue>
        </div>
      </div>
    </section>
  )
}

// ---------- S05 floor: the camera rises to the overhead plan; the sign opens the dashboard ----------

const PIN_LABEL: Record<string, string> = {
  stone: 'empty',
  leaf: 'served, on track',
  bone: 'task waiting for accept',
  red: 'escalated, needs the manager',
}

export function Floor({ index, active, past, step }: SceneProps) {
  const root = useSceneRoot(index)
  const { reduced } = useStory()
  const interior = useRef<HTMLDivElement>(null)
  const overhead = useRef<HTMLDivElement>(null)
  const pins = useRef<HTMLDivElement>(null)
  const scrims = useRef<HTMLDivElement>(null)
  const copy = useRef<HTMLDivElement>(null)
  const sign = useRef<HTMLDivElement>(null)
  useFrame((g) => {
    const l = floorLayers(root.local(g))
    place(interior.current, l.interior, PLATE0[2])
    show(interior.current, l.interiorOpacity)
    place(overhead.current, l.overhead, 1600)
    show(overhead.current, l.overheadOpacity)
    show(pins.current, l.pins)
    show(scrims.current, l.copy)
    show(copy.current, l.copy)
    show(sign.current, l.sign)
  })
  return (
    <section ref={root.ref} className="scene floor" aria-label="The live floor">
      <div className="cover">
        <div className="plate" ref={interior}>
          <img src={asset('interior.jpg')} alt="" />
        </div>
        <div className="overhead" ref={overhead}>
          <img src={asset('overhead.jpg')} alt="Overhead plan of the dining room with eight tables" />
          <div ref={pins} className="layer" style={{ width: 1600, height: 900 }}>
            {PINS.map((p) => (
              <div
                key={p.id}
                className="pin"
                data-tone={p.tone}
                style={{ left: p.x + 80, top: p.y }}
                title={`Table ${p.id}: ${PIN_LABEL[p.tone]}`}
              >
                {p.id}
              </div>
            ))}
          </div>
        </div>
        <div ref={scrims}>
          <div
            className="scrim"
            style={{ left: 0, top: 76, width: 1440, height: 150, background: 'linear-gradient(180deg, #0b0b0ab3, #0b0b0a00)' }}
          />
          <div
            className="scrim"
            style={{ left: 0, top: 540, width: 1440, height: 360, background: 'linear-gradient(180deg, #0b0b0a00, #0b0b0ae0)' }}
          />
        </div>
      </div>
      <div className="fit">
        <div ref={copy}>
          <div className="caption">LIVE FLOOR · 8 TABLES</div>
          <Heading
            className="title"
            text="Every table. One live picture."
            live={active && step >= 3}
            past={past}
            align="center"
          />
        </div>
        <div ref={sign} className="sign">
          <Magnet padding={60} magnetStrength={5} disabled={reduced}>
            <a className="sign__card" href={links.dashboard}>
              <img src={asset('logo-ink.png')} alt="" />
              <span className="sign__rule" />
              <span className="sign__text">
                <ShinyText color="#0b0b0a" shineColor="#e4543e" speed={3}>
                  OPEN LIVE DASHBOARD →
                </ShinyText>
              </span>
            </a>
          </Magnet>
        </div>
      </div>
    </section>
  )
}
