import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
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
