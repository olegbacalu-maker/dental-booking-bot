import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { hookPrint } from '../utils/flip'
import { motionOk, stepMs } from '../utils/motion'

/* jsdom не умеет showModal/close: тогда открываем атрибутом — форма та же.
   Одни и те же две функции у всех диалогов бандла: фиша (`patients/card`),
   «Pacient nou», окно подтверждения (`ConfirmHost`). */
export function showDialog(d: HTMLDialogElement | null) {
  if (!d || d.open) return
  if (typeof d.showModal === 'function') d.showModal()
  else d.setAttribute('open', '')
}

export function hideDialog(d: HTMLDialogElement | null) {
  if (!d || !d.open) return
  if (typeof d.close === 'function') d.close()
  else d.removeAttribute('open')
}

/* Откуда открыли окно: блок сетки дня, строка повестки, пустой час. Тот, по чему
   щёлкнули, называет себя (`noteOrigin`) перед тем, как попросить окно; окно,
   открывшееся следом, вырастает из него и сворачивается обратно в него —
   видно, чьё оно. Источник одноразовый и недолгий: окно, открытое позже или из
   другого места (меню, шапка), ведёт себя как обычно. */
const ORIGIN_MS = 600
const GROW_MS = 280
let origin: { el: Element; at: number } | null = null

export function noteOrigin(el: Element | null): void {
  origin = el ? { el, at: performance.now() } : null
}

/** Сдвиг и масштаб, при которых окно ложится на источник. Место окна — раскладкой:
 *  прямоугольник экрана видел бы его посреди перехода появления. */
function ontoOrigin(d: HTMLDialogElement, el: Element): string {
  const f = el.getBoundingClientRect()
  const r2 = (n: number) => Math.round(n * 100) / 100
  return `translate(${r2(f.left - d.offsetLeft)}px, ${r2(f.top - d.offsetTop)}px) `
    + `scale(${r2(f.width / (d.offsetWidth || 1))}, ${r2(f.height / (d.offsetHeight || 1))})`
}

/**
 * Открыть и закрыть окно по `open` — и, если его открыли из названного
 * источника, вырастить из него и свернуть в него.
 *
 * Раскрытие — Web Animations (место источника известно только здесь).
 * Сворачивание — переход CSS: сюда пишется лишь, КУДА (`--grow-to`), а ведёт
 * общий переход окна из panel.css. Так закрытие гаснет правилом печати в том
 * же кадре, и хозяин, ждущий конца перехода окна, ждёт и сворачивание.
 * Без движения — открыть и закрыть, как прежде.
 */
export function useDialogFromOrigin(ref: RefObject<HTMLDialogElement | null>, open: boolean): void {
  const from = useRef<Element | null>(null)
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (!open) {
      const el = from.current
      from.current = null
      /* по Esc окно закрыл сам браузер, раньше этого эффекта: оно ещё стоит на месте и гаснет */
      const to = el && el.isConnected && d.offsetWidth > 0 && motionOk() ? ontoOrigin(d, el) : ''
      hideDialog(d)
      if (to) {
        d.style.setProperty('--grow-to', to)
        d.setAttribute('data-grow', '')
      }
      return
    }
    d.removeAttribute('data-grow')
    d.style.removeProperty('--grow-to')
    showDialog(d)
    const o = origin
    origin = null
    from.current = null
    if (!o || performance.now() - o.at > ORIGIN_MS || !o.el.isConnected) return
    if (!motionOk() || typeof d.animate !== 'function') return
    from.current = o.el
    hookPrint()
    d.animate(
      [{ transformOrigin: '0 0', transform: ontoOrigin(d, o.el) }, { transformOrigin: '0 0', transform: 'none' }],
      { duration: GROW_MS, easing: 'cubic-bezier(.2,.8,.2,1)' })
  }, [ref, open])
}

/**
 * Закрытие окна, которое хозяин монтирует условно (`{open && <Окно/>}`).
 * Хозяин снимает узел, как только узнал о закрытии, и переход закрытия из
 * panel.css не успевает сыграть: окно пропадает одним кадром. Поэтому хозяину
 * говорят «закрыто» после конца перехода самого окна; запасной таймер на ту же
 * ступень — для движка без `allow-discrete` и для печати, где перехода нет
 * (идущий переход таймер не обрывает — дожидается его).
 * Движение выключено системой (и в jsdom) — хозяин узнаёт сразу, как раньше.
 *
 * `leave` зовут все пути закрытия, в том числе событие `close` самого окна
 * (Esc без своего обработчика): повторный вызов ничего не делает.
 * `leaving` — окно уже закрыто и доигрывает: несохранённым оно больше не считается.
 */
export function useDialogLeave(ref: RefObject<HTMLDialogElement | null>, onClose: () => void):
  { leave: () => void; leaving: boolean } {
  const [leaving, setLeaving] = useState(false)
  const done = useRef(onClose)
  useEffect(() => { done.current = onClose })
  const gone = useRef(false)
  const drop = useRef<(() => void) | null>(null)
  useEffect(() => () => drop.current?.(), [])

  const leave = useCallback(() => {
    if (gone.current) return
    gone.current = true
    const d = ref.current
    hideDialog(d)
    if (!d || !motionOk()) {
      done.current()
      return
    }
    setLeaving(true)
    const win = d
    let over = false
    let timer = 0
    function stop() {
      over = true
      window.clearTimeout(timer)
      win.removeEventListener('transitionend', onEnd)
      drop.current = null
    }
    function finish() {
      if (over) return
      stop()
      done.current()
    }
    /* переходы детей всплывают сюда же; у окна их несколько — ждём прозрачность */
    function onEnd(e: TransitionEvent) {
      if (e.target === win && e.propertyName === 'opacity') finish()
    }
    /* Срок вышел, а переход ещё идёт: после записи экран перерисовывается, и переход
       начинается позже щелчка. Срок — запасной, окно снимается по концу перехода. */
    function late() {
      const fading = typeof win.getAnimations === 'function'
        ? win.getAnimations().filter((a) => a.playState === 'running' && (a as CSSTransition).transitionProperty === 'opacity')
        : []
      if (fading.length === 0) finish()
      else void Promise.allSettled(fading.map((a) => a.finished)).then(finish)
    }
    timer = window.setTimeout(late, stepMs('--dur-fast'))
    win.addEventListener('transitionend', onEnd)
    drop.current = stop
  }, [ref])

  return { leave, leaving }
}
