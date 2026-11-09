import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { Icon } from '../../../../components/Icon'

/* Поле подписи (09.11). Палец, перо, мышь — одни Pointer Events;
   `touch-action: none` в CSS, иначе палец прокручивает окно вместо линии.
   Холст в пикселях экрана (ретина: размер × devicePixelRatio), линия —
   сглаженная квадратичными кривыми через середины соседних точек.
   ⛔ Наружу уходит ТОЛЬКО картинка (`png()`): нажим, скорость и время точек
   не собираются вовсе — иначе это биометрия по закону 195. Точки живут в
   памяти поля лишь затем, чтобы перерисовать линию при смене размера. */

export interface SignPadHandle {
  /** PNG с прозрачным фоном; пустое поле — null. */
  png: () => string | null
}

interface Props {
  title: string
  sub?: string
  /** подсказка внутри пустого поля */
  placeholder: string
  clearLabel: string
  onChange: (empty: boolean) => void
}

type Pt = [number, number]

function pen(c: HTMLCanvasElement) {
  const g = c.getContext('2d')
  if (!g) return null
  const k = c.width / Math.max(1, c.clientWidth)
  g.setTransform(k, 0, 0, k, 0, 0)
  g.lineCap = 'round'
  g.lineJoin = 'round'
  g.lineWidth = 2.4
  g.strokeStyle = getComputedStyle(c).color || '#1d2b53'
  return g
}

function stroke(g: CanvasRenderingContext2D, s: Pt[]) {
  const first = s[0]
  if (!first) return
  g.beginPath()
  g.moveTo(first[0], first[1])
  if (s.length === 1) {
    g.lineTo(first[0] + 0.1, first[1] + 0.1)
  } else {
    for (let i = 1; i < s.length - 1; i++) {
      const p = s[i]!, q = s[i + 1]!
      g.quadraticCurveTo(p[0], p[1], (p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    }
    const last = s[s.length - 1]!
    g.lineTo(last[0], last[1])
  }
  g.stroke()
}

function paint(c: HTMLCanvasElement, all: Pt[][]) {
  const g = c.getContext('2d')
  if (!g) return
  g.setTransform(1, 0, 0, 1, 0, 0)
  g.clearRect(0, 0, c.width, c.height)
  const p = pen(c)
  if (p) for (const s of all) stroke(p, s)
}

function at(c: HTMLCanvasElement, e: { clientX: number; clientY: number }): Pt {
  const r = c.getBoundingClientRect()
  return [e.clientX - r.left, e.clientY - r.top]
}

export const SignPad = forwardRef<SignPadHandle, Props>(function SignPad(
  { title, sub = '', placeholder, clearLabel, onChange }, ref,
) {
  const cv = useRef<HTMLCanvasElement>(null)
  const strokes = useRef<Pt[][]>([])
  const cur = useRef<Pt[] | null>(null)
  const [inked, setInked] = useState(false)

  useEffect(() => {
    const c = cv.current
    if (!c) return
    const fit = () => {
      const r = c.getBoundingClientRect()
      const dpr = window.devicePixelRatio || 1
      const w = Math.round(r.width * dpr), h = Math.round(r.height * dpr)
      if (w && h && (c.width !== w || c.height !== h)) { c.width = w; c.height = h; paint(c, strokes.current) }
    }
    fit()
    if (typeof ResizeObserver !== 'function') return
    const ro = new ResizeObserver(fit)
    ro.observe(c)
    return () => ro.disconnect()
  }, [])

  useImperativeHandle(ref, () => ({
    png() {
      const c = cv.current
      return strokes.current.length && c ? c.toDataURL('image/png') : null
    },
  }), [])

  function clear() {
    strokes.current = []
    cur.current = null
    if (cv.current) paint(cv.current, [])
    setInked(false)
    onChange(true)
  }

  function down(e: React.PointerEvent<HTMLCanvasElement>) {
    if (e.pointerType === 'mouse' && e.button !== 0) return
    e.preventDefault()
    const c = e.currentTarget
    c.setPointerCapture?.(e.pointerId)
    cur.current = [at(c, e)]
    strokes.current.push(cur.current)
    const g = pen(c)
    if (g) stroke(g, cur.current)
  }

  function move(e: React.PointerEvent<HTMLCanvasElement>) {
    const s = cur.current
    if (!s) return
    e.preventDefault()
    const c = e.currentTarget
    const n = e.nativeEvent
    const evs = typeof n.getCoalescedEvents === 'function' ? n.getCoalescedEvents() : []
    for (const ev of evs.length ? evs : [n]) s.push(at(c, ev))
    const g = pen(c)
    /* дорисовать хвост штриха, а не весь холст */
    if (g) stroke(g, s.slice(-4))
  }

  function up(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!cur.current) return
    cur.current = null
    paint(e.currentTarget, strokes.current)
    if (!inked) { setInked(true); onChange(false) }
  }

  return (
    <div className="sg-pad">
      <div className="sg-padh">
        <b>{title}</b>{sub && <small>{sub}</small>}
        <button type="button" className="pl-btn sg-clear" onClick={clear} disabled={!inked}>
          <Icon name="erase" /> {clearLabel}
        </button>
      </div>
      <div className={`dp-sigpad${inked ? ' inked' : ''}`}>
        <canvas ref={cv} aria-label={title} role="img"
          onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} />
        <span className="ph" aria-hidden="true">{placeholder}</span>
        <span className="base" aria-hidden="true" />
      </div>
    </div>
  )
})
