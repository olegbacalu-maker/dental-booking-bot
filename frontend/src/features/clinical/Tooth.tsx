import type { CSSProperties, MouseEvent } from 'react'
import type { ToothInfo, View } from './chart'

/*
 * Один зуб = слои поверх серверной геометрии:
 *   геометрия      — SVG сервера (innerHTML; константа нашего же движка, не
 *                    данные пользователя — заметка в нём не живёт);
 *   поверхности    — цели `data-s` внутри SVG (teeth_svg.surface_hits): клик
 *                    по ним даёт букву, без знания геометрии;
 *   состояние      — классы tooth-{state} и ореолы уже в SVG;
 *   выбор          — классы sel / br-pick на кнопке;
 *   аннотация      — номер со стороны корней и подпись сервера в title.
 * Разметка кнопки — та же, что у старой страницы (.tooth-btn, .num), поэтому
 * panel.css красит её без единого нового правила.
 */
interface Props {
  n: number
  info: ToothInfo
  view: View
  selected?: boolean
  picked?: boolean
  /** Нижняя дуга: номер идёт ПОСЛЕ рисунка (со стороны корней). */
  lower?: boolean
  /** Подъём в виде сверху, px (переменная --arc, как у старой страницы). */
  arc?: number
  onSelect?: (n: number) => void
  /** Клик по поверхности внутри рисунка. */
  onSurface?: (n: number, letter: string) => void
  onHover?: (n: number, el: HTMLElement | null) => void
}

export function Tooth({ n, info, view, selected, picked, lower, arc, onSelect, onSurface, onHover }: Props) {
  const svg = view === 'ocluzal' ? info.svg.occlusal : info.svg.frontal
  const num = `<span class='num'>${n}</span>`
  const html = lower ? svg + num : num + svg
  const cls = `tooth-btn${selected ? ' sel' : ''}${picked ? ' br-pick' : ''}`
  const style = arc ? ({ '--arc': `${arc}px` } as CSSProperties) : undefined

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
      onMouseEnter={onHover ? (e) => onHover(n, e.currentTarget) : undefined}
      onMouseLeave={onHover ? () => onHover(n, null) : undefined}
      onFocus={onHover ? (e) => onHover(n, e.currentTarget) : undefined}
      onBlur={onHover ? () => onHover(n, null) : undefined}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
