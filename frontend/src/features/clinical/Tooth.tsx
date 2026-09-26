import type { CSSProperties, MouseEvent } from 'react'
import type { ToothVisual, View } from './chart'
import { useLongPress } from './touch'

/*
 * Один зуб = слои поверх серверной геометрии:
 *   геометрия      — SVG сервера (innerHTML; константа нашего же движка, не
 *                    данные пользователя — заметка в нём не живёт);
 *   поверхности    — цели `data-s` внутри SVG (teeth_svg.surface_hits): клик
 *                    по ним даёт букву, без знания геометрии;
 *   состояние      — классы tooth-{state} и ореолы уже в SVG;
 *   выбор          — классы sel / br-pick / dirty на кнопке;
 *   аннотация      — номер со стороны корней и подпись сервера в title.
 * Разметка кнопки — та же, что у старой страницы (.tooth-btn, .num), поэтому
 * panel.css красит её без единого нового правила. Правая кнопка (C22) —
 * контекстное меню родителя; путь не единственный, то же есть в инспекторе.
 * Пальцем (B7 · планшет) меню открывает ДОЛГОЕ НАЖАТИЕ — iPad contextmenu
 * на нём не шлёт (`touch.useLongPress`).
 */
interface Props {
  n: number
  /** Рисунок и подпись: `ToothInfo` одонтограммы или зуб пародонтограммы. */
  info: ToothVisual
  view: View
  selected?: boolean
  picked?: boolean
  /** Есть незаписанная правка (черновик). */
  dirty?: boolean
  /** Нижняя дуга: номер идёт ПОСЛЕ рисунка (со стороны корней). */
  lower?: boolean
  /** Подъём в виде сверху, px (переменная --arc, как у старой страницы). */
  arc?: number
  onSelect?: (n: number) => void
  /** Клик по поверхности внутри рисунка. */
  onSurface?: (n: number, letter: string) => void
  onHover?: (n: number, el: HTMLElement | null) => void
  /** Меню зуба у точки: правая кнопка мыши или долгое нажатие пальцем. */
  onMenu?: (n: number, x: number, y: number) => void
}

export function Tooth({ n, info, view, selected, picked, dirty, lower, arc, onSelect, onSurface, onHover, onMenu }: Props) {
  const svg = view === 'ocluzal' ? info.svg.occlusal : info.svg.frontal
  const num = `<span class='num'>${n}</span>`
  const html = lower ? svg + num : num + svg
  const cls = `tooth-btn${selected ? ' sel' : ''}${picked ? ' br-pick' : ''}${dirty ? ' dirty' : ''}`
  const style = arc ? ({ '--arc': `${arc}px` } as CSSProperties) : undefined
  const press = useLongPress(onMenu ? (x, y) => onMenu(n, x, y) : undefined)

  function onClick(e: MouseEvent<HTMLButtonElement>) {
    const target = e.target as Element
    const hit = typeof target.closest === 'function' ? target.closest('[data-s]') : null
    const letter = hit?.getAttribute('data-s')
    if (letter && onSurface) {
      onSurface(n, letter)
      return
    }
    onSelect?.(n)
  }

  return (
    <button
      type="button"
      className={cls}
      data-n={n}
      style={style}
      title={info.title}
      onClick={onClick}
      onContextMenu={onMenu ? (e) => { e.preventDefault(); onMenu(n, e.clientX, e.clientY) } : undefined}
      {...press}
      onMouseEnter={onHover ? (e) => onHover(n, e.currentTarget) : undefined}
      onMouseLeave={onHover ? () => onHover(n, null) : undefined}
      onFocus={onHover ? (e) => onHover(n, e.currentTarget) : undefined}
      onBlur={onHover ? () => onHover(n, null) : undefined}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
