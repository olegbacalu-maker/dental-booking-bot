/**
 * Уход с экрана (вторая волна плавности, 07.11.2026): окно, меню, плашка и
 * строка списка не исчезают в том же кадре, а доигрывают короткий переход.
 *
 * ⛔ React размонтирует узел сразу, и CSS доиграть не успевает — поэтому
 * родитель держит значение ещё одну ступень (`useLingering`), а узел в это
 * время стоит с признаком «уходит» (`open={false}`, класс `out`), и переход
 * идёт по CSS. Ввод при этом не задержан: закрытое окно не модально, у
 * уходящего узла `pointer-events:none`, следующий щелчок работает сразу.
 * ⛔ Движение — только когда его разрешила система: при
 * `prefers-reduced-motion` и в движке без `matchMedia` (jsdom в проверках)
 * уход мгновенный, как было.
 */
import { useEffect, useState } from 'react'

/** Разрешено ли движение: система не просит меньше, движок умеет `matchMedia`. */
export function motionOk(): boolean {
  try {
    return typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: no-preference)').matches
  } catch {
    return false
  }
}

/** Ступень длительности из `:root` (panel.css), в миллисекундах; запас — чтобы
 *  узел ушёл ПОСЛЕ конца перехода, а не на его последнем кадре. */
export function stepMs(name: '--dur-fast' | '--dur' | '--dur-slow' = '--dur-fast'): number {
  const fallback = { '--dur-fast': 150, '--dur': 200, '--dur-slow': 250 }[name]
  try {
    const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    const n = raw.endsWith('ms') ? parseFloat(raw) : raw.endsWith('s') ? parseFloat(raw) * 1000 : NaN
    return (Number.isFinite(n) && n >= 0 ? n : fallback) + 40
  } catch {
    return fallback + 40
  }
}

/**
 * Значение на момент, когда ключ стал этим (открытие окна или меню).
 * ⛔ Зачем: уходящее окно гаснет с тем, что человек видел, а не с тем, что уже
 * приехало: ответ команды и конверт канала успевают за эту ступень, и окно
 * сменило бы кнопки и высоту прямо во время затухания.
 */
export function useOpening<T>(key: unknown, live: T): T {
  const [held, setHeld] = useState({ key, value: live })
  if (held.key !== key) {
    setHeld({ key, value: live })
    return live
  }
  return held.value
}

/**
 * Держать ушедшее значение ещё одну ступень: `shown` — что рисовать (текущее
 * или уходящее), `leaving` — что оно уходит. Без движения `shown === value`.
 * ⚠️ Решение «держать или нет» принимается при смене значения, на рендере
 * (приём «состояние от прошлого рендера»), таймер — эффектом.
 */
export function useLingering<T>(value: T | null, step: '--dur-fast' | '--dur' = '--dur-fast'):
  { shown: T | null; leaving: boolean } {
  const [prev, setPrev] = useState<T | null>(value)
  const [ghost, setGhost] = useState<T | null>(null)
  if (value !== prev) {
    setPrev(value)
    setGhost(value === null && prev !== null && motionOk() ? prev : null)
  }
  useEffect(() => {
    if (ghost === null) return
    const t = window.setTimeout(() => setGhost(null), stepMs(step))
    return () => window.clearTimeout(t)
  }, [ghost, step])
  const leaving = value === null && ghost !== null
  return { shown: value ?? (leaving ? ghost : null), leaving }
}
