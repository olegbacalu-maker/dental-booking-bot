import type { LegendItem } from './chart'

/* Легенда показывает НАСТОЯЩИЙ зуб в каждом состоянии, потом отметки на
   здоровом зубе за разделителем — та же разметка, что у старой страницы
   (.lg, .lg-sep). Рисунок и подпись — сервера.
   С 01.10 пункт — КНОПКА-ФИЛЬТР (`onPick`): нажатый гасит на дуге и в 3D все
   зубы не про него, повторное нажатие снимает; счётчик — сколько зубов на
   экране про этот пункт (`counts`, считает рабочий стол по модели). Без
   `onPick` легенда остаётся надписью, как была. */
interface Props {
  items: LegendItem[]
  /** ключ нажатого пункта; null — фильтра нет */
  active?: string | null
  counts?: Record<string, number>
  onPick?: (key: string) => void
}

const T = { filter: 'Arată doar dinții cu', all: 'toți dinții' } as const

export function Legend({ items, active = null, counts, onPick }: Props) {
  const states = items.filter((it) => it.kind === 'state')
  const marks = items.filter((it) => it.kind === 'mark')
  const one = (it: LegendItem) => {
    const n = counts?.[it.key]
    const on = active === it.key
    const inner = (
      <>
        <span className="lg-pic" dangerouslySetInnerHTML={{ __html: it.svg }} />
        <span className="lg-l">{it.label}</span>
        {n !== undefined && n > 0 && <i className="lg-n">{n}</i>}
      </>
    )
    if (!onPick) return <span key={it.key} className="lg">{inner}</span>
    return (
      <button key={it.key} type="button" className={`lg${on ? ' on' : ''}`} aria-pressed={on}
        title={on ? T.all : `${T.filter} „${it.label}"`} onClick={() => onPick(it.key)}>
        {inner}
      </button>
    )
  }
  return (
    <>
      {states.map(one)}
      <span className="lg-sep"></span>
      {marks.map(one)}
    </>
  )
}
