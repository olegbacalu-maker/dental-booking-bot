/**
 * Смыкание и переезд: узлы, сменившие место между двумя отрисовками, доезжают
 * до нового места сдвигом (приём FLIP: измерить до, измерить после, сыграть
 * разницу). Вторая волна плавности, 07.11.2026.
 *
 * ⛔ Только `transform` через Web Animations без заполнения: раскладку узел не
 * трогает, а по концу движения на нём не остаётся ничего — стенд сдвигов видит
 * тот же конечный кадр. Высота и ширина не анимируются: их читает перемер
 * ступеней блока (`useFitAppts`).
 * ⛔ На опросе без изменений места те же — ни одного запуска. Первая отрисовка
 * контейнера ничего не двигает: сравнивать не с чем.
 * ⛔ Без движения (`prefers-reduced-motion`, jsdom) — ничего, как было.
 * Выключатель стилем: `--motion-flip: none` у контейнера (пара стенда).
 */
import { useLayoutEffect, useRef, type RefObject } from 'react'
import { motionOk, stepMs } from './motion'

interface Spot { x: number; y: number }

/* Печать посреди сдвига (07.11): CSS `animation:none` в `@media print` Web
   Animations не касается, и лист снял бы строку на полпути. Перед печатью
   сдвиги завершаются — узел встаёт на своё место. Один слушатель на окно. */
let printHooked = false
function hookPrint(): void {
  if (printHooked || typeof window.matchMedia !== 'function') return
  printHooked = true
  const finish = () => {
    for (const a of document.getAnimations()) {
      const css = a as Partial<CSSAnimation & CSSTransition>
      if (!css.animationName && !css.transitionProperty) a.finish()
    }
  }
  window.matchMedia('print').addEventListener('change', (e) => { if (e.matches) finish() })
  window.addEventListener('beforeprint', finish)
}

/** Место узла В РАСКЛАДКЕ, без учёта идущего transform: по цепочке
 *  `offsetParent` до контейнера. ⛔ Не `getBoundingClientRect`: тот видит
 *  узел на полпути, и повторный рендер во время движения (тик, ответ канала)
 *  перезапускал бы сдвиг от текущего кадра — узел застывал у старта. */
function layoutSpot(el: HTMLElement, root: HTMLElement): Spot {
  let x = 0
  let y = 0
  let node: HTMLElement | null = el
  while (node && node !== root) {
    x += node.offsetLeft
    y += node.offsetTop
    node = node.offsetParent as HTMLElement | null
  }
  return { x, y }
}

export function useFlip(
  box: RefObject<HTMLElement | null>, dep: unknown, selector = '[data-appt]',
  step: '--dur-fast' | '--dur' = '--dur',
): void {
  const last = useRef<Map<string, Spot> | null>(null)
  useLayoutEffect(() => {
    const root = box.current
    if (!root) return
    const now = new Map<string, Spot>()
    const nodes: [HTMLElement, string][] = []
    for (const el of root.querySelectorAll<HTMLElement>(selector)) {
      if (el.classList.contains('leaving')) continue        // призрак ушедшей строки — не узел списка
      const key = el.getAttribute('data-appt') ?? ''
      now.set(key, layoutSpot(el, root))
      nodes.push([el, key])
    }
    const was = last.current
    last.current = now
    if (!was || !motionOk() || typeof root.animate !== 'function'
      || getComputedStyle(root).getPropertyValue('--motion-flip').trim() === 'none') return
    hookPrint()
    const ms = stepMs(step) - 40
    for (const [el, key] of nodes) {
      const from = was.get(key)
      const to = now.get(key)!
      if (!from) {
        /* новый узел между старыми (приехал с другого места) — проявляется;
           на первой отрисовке контейнера `was` пуст, и сюда не доходит */
        el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: ms, easing: 'ease' })
        continue
      }
      const dx = from.x - to.x
      const dy = from.y - to.y
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue
      el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }],
        { duration: ms, easing: 'cubic-bezier(.22,.61,.36,1)' })
    }
  }, [box, dep, selector, step])
}
