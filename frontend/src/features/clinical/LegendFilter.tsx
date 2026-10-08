import type { LegendItem } from './chart'

/* Легенда-фильтр под вьюпортом (08.10, макет): чип = цветной квадрат,
   подпись, счётчик. Нажатый гасит на карте, дуге и в сцене все зубы не про
   него, повторное нажатие снимает (01.10). Состояния и отметки — одним
   рядом в порядке сервера; цвет — его палитра (та же, что у 2D, 3D и
   043/e). Рисунок зуба в легенде (до 08.10) остался на печати. Счётчик —
   число зубов на экране про этот пункт (считает рабочий стол), ноль не
   печатается. */
const T = { filter: 'Arată doar dinții cu', all: 'toți dinții' } as const

interface Props {
  items: LegendItem[]
  palette?: Record<string, string> | undefined
  /** ключ нажатого пункта; null — фильтра нет */
  active: string | null
  counts: Record<string, number>
  onPick: (key: string) => void
}

export function LegendFilter({ items, palette, active, counts, onPick }: Props) {
  return (
    <>
      {items.map((it) => {
        const n = counts[it.key] ?? 0
        const on = active === it.key
        return (
          <button key={it.key} type="button" className={`lg dp-leg${on ? ' on' : ''}`} aria-pressed={on}
            title={on ? T.all : `${T.filter} „${it.label}"`} onClick={() => onPick(it.key)}>
            <i className="sw" style={{ background: palette?.[it.key] ?? 'currentColor' }} />
            <span className="lg-l">{it.label}</span>
            {n > 0 && <i className="lg-n">{n}</i>}
          </button>
        )
      })}
    </>
  )
}
