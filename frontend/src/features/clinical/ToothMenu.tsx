import { Fragment, useRef, type ReactNode } from 'react'
import { Icon } from '../../components/Icon'
import { placeMenu, useMenuDismiss } from '../../components/menu'
import { useCoarse } from './touch'
import type { ChartMode, Odontogram } from './chart'

/* Контекстное меню зуба (C22): состояния зуба — в ЧЕРНОВИК (запись — Save
   или Enter, как и у всего остального), под чертой — отметки поверх находки
   (02.10: «Nerv extras» искали именно здесь, на самом зубе, — а была только
   галочка в инспекторе), «Adaugă în plan» (01.10: позиция плана с этого зуба)
   и «Punte nouă de la acest dinte». Состояние — одно (radio), отметки
   независимы (checkbox): кариес и «nerv extras» живут на зубе вместе.
   Списки состояний и отметок — сервера, своего словаря здесь нет. Меню не
   единственный путь: то же есть в инспекторе (touch, доступность).
   Закрывается кликом мимо, Esc, прокруткой и сменой размера окна.

   Под режим экрана (24.10): пункты режима — первыми. Группа (состояния /
   отметки / действия), где они есть, встаёт наверх, внутри группы — они
   впереди; черты между группами остаются, ничего не пропадает. Режим назван
   в шапке меню — порядок меняется не сам по себе. */
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
  /** режим экрана: его пункты — первыми */
  mode?: ChartMode | null
}

const WIDTH = 236

/** Пункты режима вперёд, остальные — в прежнем порядке сервера. */
function hotFirst(items: [string, string][], hot: ReadonlySet<string>): [string, string][] {
  return [...items.filter(([k]) => hot.has(k)), ...items.filter(([k]) => !hot.has(k))]
}

export function ToothMenu({ model, at, current, onState, marks, onMark, onPlan, onBridge, onClose, mode = null }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  useMenuDismiss(ref, onClose)
  // строка меню: 32 px мышью, 44 px пальцем (та же высота задана в app.css)
  const ROW = useCoarse() ? 44 : 32

  const info = model.teeth[String(at.n)]
  // в меню — состояния про весь зуб; кариес и пломба ставятся кистью по поверхностям (11.10)
  const keyed = mode?.kind === 'keys' ? mode : null
  const hot = new Set(keyed?.keys ?? [])
  const states = hotFirst(Object.entries(model.tooth_states), hot)
  const markList = hotFirst(Object.entries(model.marks), hot)
  const bridge = Boolean(info && !info.milk)
  const bridgeHot = bridge && Boolean(keyed?.bridges)
  const extra = (onPlan ? ROW : 0) + (bridge ? ROW : 0)
  const height = 40 + states.length * ROW + (markList.length ? markList.length * ROW + 9 : 0)
    + (extra ? extra + 9 : 0) + 12
  const { left, top } = placeMenu(at.x, at.y, WIDTH, height)

  const planItem = onPlan && (
    <button key="plan" type="button" role="menuitem" className="dp-cmenu-i" onClick={() => onPlan(at.n)}>
      <Icon name="clipboard" /> {T.plan}
    </button>
  )
  const bridgeItem = bridge && (
    <button key="bridge" type="button" role="menuitem" className="dp-cmenu-i" onClick={() => onBridge(at.n)}>{T.bridgeFrom}</button>
  )
  const groups: { hot: boolean; items: ReactNode[] }[] = [
    {
      hot: states.some(([k]) => hot.has(k)),
      items: states.map(([k, v]) => (
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
      )),
    },
    {
      hot: markList.some(([k]) => hot.has(k)),
      items: markList.map(([k, v]) => (
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
      )),
    },
    { hot: bridgeHot, items: (bridgeHot ? [bridgeItem, planItem] : [planItem, bridgeItem]).filter(Boolean) },
  ].filter((g) => g.items.length > 0)
  // сортировка устойчива: группы без пунктов режима сохраняют прежний порядок
  groups.sort((a, b) => Number(b.hot) - Number(a.hot))
  const lead = keyed && groups.some((g) => g.hot) ? keyed.label : ''
  return (
    <div ref={ref} className="dp-cmenu" role="menu" aria-label={`${T.tooth} ${at.n}`} style={{ left, top, width: WIDTH }}>
      <div className="dp-cmenu-h">{T.tooth} {at.n}{lead && <span className="dp-cmenu-mode"> · {lead}</span>}</div>
      {groups.map((g, i) => (
        <Fragment key={i}>
          {i > 0 && <div className="dp-cmenu-sep" />}
          {g.items}
        </Fragment>
      ))}
    </div>
  )
}
