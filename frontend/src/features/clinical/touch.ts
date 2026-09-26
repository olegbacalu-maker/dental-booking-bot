import { useEffect, useRef, useState, type MouseEvent, type PointerEvent } from 'react'

/* Одонтограмма под палец (B7 · планшет, 26.09.2026). Олег стоял у кресла:
   «у него прямо над креслом планшет… включил программу и быстро записал данные
   по одонтограмме»; iPad и Android — «надо сделать на оба». Всё здесь
   включается ТОЛЬКО для касания и пера: рабочий стол мышью не меняется.
   Сам режим «у кресла» — отдельная работа (сессия «сетевая настройка»). */

/** Удержание, после которого касание — «долгое нажатие», мс. */
export const LONG_MS = 500
/** Сдвиг пальца, после которого касание — протяжка, а не нажатие, px. Для мыши
 *  порог 4 px: палец дрожит сильнее, и на 4 px выбор зуба крутил бы сцену. */
export const TOUCH_SLOP = 10
export const MOUSE_SLOP = 4

/** Палец или перо (у мыши — правая кнопка и наведение). */
export const isFinger = (e: { pointerType?: string }): boolean => e.pointerType === 'touch' || e.pointerType === 'pen'

export const slopOf = (e: { pointerType?: string }): number => (isFinger(e) ? TOUCH_SLOP : MOUSE_SLOP)

const COARSE = '(pointer: coarse)'

/** Основное устройство ввода — палец (планшет): медиазапрос `(pointer: coarse)`
 *  с подпиской на смену. Без matchMedia (jsdom) — мышь. */
export function useCoarse(): boolean {
  const [on, setOn] = useState(() => typeof window.matchMedia === 'function' && window.matchMedia(COARSE).matches)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const q = window.matchMedia(COARSE)
    const f = (): void => setOn(q.matches)
    q.addEventListener?.('change', f)
    return () => q.removeEventListener?.('change', f)
  }, [])
  return on
}

/**
 * Погасить ПЕРВЫЙ click после сработавшего долгого нажатия, куда бы он ни
 * пришёлся: отпускание пальца рождает совместимый click в точке касания, а
 * там теперь меню — у края окна оно сдвинуто, и click попал бы в ПУНКТ меню
 * (молча сменил бы состояние зуба). Слушатель на документе в фазе захвата,
 * одноразовый; если click так и не пришёл (Safari), снимается сам через 1,5 с.
 */
export function swallowNextClick(): void {
  let timer: ReturnType<typeof setTimeout> | null = null
  const done = (): void => {
    document.removeEventListener('click', eat, true)
    if (timer) clearTimeout(timer)
  }
  const eat = (e: Event): void => {
    e.preventDefault()
    e.stopPropagation()
    done()
  }
  document.addEventListener('click', eat, true)
  timer = setTimeout(done, 1500)
}

export interface LongPress {
  onPointerDown?: (e: PointerEvent<HTMLElement>) => void
  onPointerMove?: (e: PointerEvent<HTMLElement>) => void
  onPointerUp?: () => void
  onPointerCancel?: () => void
  onClickCapture?: (e: MouseEvent<HTMLElement>) => void
  onContextMenuCapture?: (e: MouseEvent<HTMLElement>) => void
}

/**
 * Долгое нажатие пальцем → `fire(x, y)` в точке касания.
 * ⛔ Не через contextmenu: Safari на iPad на долгом нажатии его не шлёт вовсе
 * (меню пальцем открыть было бы нечем), а Chrome на Android шлёт — поэтому
 * contextmenu после сработавшего нажатия гасится (меню открылось бы дважды).
 * Следующий click тоже гасится: отпускание пальца иначе выбрало бы зуб или
 * переключило поверхность. Мышь сюда не попадает — у неё правая кнопка.
 */
export function useLongPress(fire: ((x: number, y: number) => void) | undefined): LongPress {
  const pending = useRef<{ id: number; x: number; y: number; timer: ReturnType<typeof setTimeout> } | null>(null)
  const fired = useRef(false)
  const stop = (): void => {
    if (pending.current) {
      clearTimeout(pending.current.timer)
      pending.current = null
    }
  }
  useEffect(() => stop, [])
  if (!fire) return {}
  return {
    onPointerDown(e) {
      fired.current = false
      if (!isFinger(e)) return
      stop()
      const x = e.clientX
      const y = e.clientY
      const timer = setTimeout(() => {
        pending.current = null
        fired.current = true
        swallowNextClick()
        fire(x, y)
      }, LONG_MS)
      pending.current = { id: e.pointerId, x, y, timer }
    },
    onPointerMove(e) {
      const p = pending.current
      if (p && p.id === e.pointerId && Math.hypot(e.clientX - p.x, e.clientY - p.y) > TOUCH_SLOP) stop()
    },
    onPointerUp: stop,
    onPointerCancel: stop,
    onClickCapture(e) {
      if (!fired.current) return
      fired.current = false
      e.preventDefault()
      e.stopPropagation()
    },
    onContextMenuCapture(e) {
      if (!fired.current) return
      e.preventDefault()
      e.stopPropagation()
    },
  }
}
