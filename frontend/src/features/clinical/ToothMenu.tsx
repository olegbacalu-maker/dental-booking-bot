import { useRef } from 'react'
import { Icon } from '../../components/Icon'
import { placeMenu, useMenuDismiss } from '../../components/menu'
import { useCoarse } from './touch'
import type { Odontogram } from './chart'

/* Контекстное меню зуба (C22): состояния зуба — в ЧЕРНОВИК (запись — Save
   или Enter, как и у всего остального), под чертой — отметки поверх находки
   (03.10: «Nerv extras» искали именно здесь, на самом зубе, — а была только
   галочка в инспекторе), «Adaugă în plan» (01.10: позиция плана с этого зуба)
   и «Punte nouă de la acest dinte». Состояние — одно (radio), отметки
   независимы (checkbox): кариес и «nerv extras» живут на зубе вместе.
   Списки состояний и отметок — сервера, своего словаря здесь нет. Меню не
   единственный путь: то же есть в инспекторе (touch, доступность).
   Закрывается кликом мимо, Esc, прокруткой и сменой размера окна. */
const T = {
  tooth: 'Dinte',
  plan: 'Adaugă în plan',
  bridgeFrom: 'Punte nouă de la acest dinte',
} as const

export interface MenuAt {
  n: number
  x: number
  y: number
}

interface Props {
  model: Odontogram
  at: MenuAt
  /** Текущее состояние зуба (черновик, если он есть) — отмечается в списке. */
  current: string
  onState: (n: number, state: string) => void
  /** Текущие отметки зуба (черновик, если он есть). */
  marks: string[]
  onMark: (n: number, mark: string) => void
  /** позиция плана с этого зуба; нет — пункта нет (экран без плана) */
  onPlan?: (n: number) => void
  onBridge: (n: number) => void
  onClose: () => void
}

const WIDTH = 236

export function ToothMenu({ model, at, current, onState, marks, onMark, onPlan, onBridge, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  useMenuDismiss(ref, onClose)
  // строка меню: 32 px мышью, 44 px пальцем (та же высота задана в app.css)
  const ROW = useCoarse() ? 44 : 32

  const info = model.teeth[String(at.n)]
  const states = Object.entries(model.states)
  const markList = Object.entries(model.marks)
  const bridge = Boolean(info && !info.milk)
  const extra = (onPlan ? ROW : 0) + (bridge ? ROW : 0)
  const height = 40 + states.length * ROW + (markList.length ? markList.length * ROW + 9 : 0)
    + (extra ? extra + 9 : 0) + 12
  const { left, top } = placeMenu(at.x, at.y, WIDTH, height)
  return (
    <div ref={ref} className="dp-cmenu" role="menu" aria-label={`${T.tooth} ${at.n}`} style={{ left, top, width: WIDTH }}>
      <div className="dp-cmenu-h">{T.tooth} {at.n}</div>
      {states.map(([k, v]) => (
        <button
          key={k}
          type="button"
          role="menuitemradio"
          aria-checked={k === current}
          className={`dp-cmenu-i${k === current ? ' on' : ''}`}
          onClick={() => onState(at.n, k)}
        >
          {v}
        </button>
      ))}
      {markList.length > 0 && <div className="dp-cmenu-sep" />}
      {markList.map(([k, v]) => (
        <button
          key={k}
          type="button"
          role="menuitemcheckbox"
          aria-checked={marks.includes(k)}
          className={`dp-cmenu-i${marks.includes(k) ? ' on' : ''}`}
          onClick={() => onMark(at.n, k)}
        >
          {v}
        </button>
      ))}
      {extra > 0 && <div className="dp-cmenu-sep" />}
      {onPlan && (
        <button type="button" role="menuitem" className="dp-cmenu-i" onClick={() => onPlan(at.n)}>
          <Icon name="clipboard" /> {T.plan}
        </button>
      )}
      {bridge && (
        <button type="button" role="menuitem" className="dp-cmenu-i" onClick={() => onBridge(at.n)}>{T.bridgeFrom}</button>
      )}
    </div>
  )
}
