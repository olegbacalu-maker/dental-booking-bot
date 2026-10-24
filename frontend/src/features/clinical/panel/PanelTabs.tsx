import type { KeyboardEvent } from 'react'

/* Вкладки панели зуба (24.10, макет B): Suprafețe / Diagnostic / Tratament /
   Notițe / Istoric. Вкладка — свойство ЭКРАНА: ни в адрес, ни в модель, ни в
   запись она не попадает и держится, пока врач ходит от зуба к зубу (смотрит
   «Diagnostic» по всей челюсти — не щёлкает её на каждом). «Imagini» концепта
   не делаем (Олег 24.10: снимок к зубу — новые данные, позже).
   Клавиатура — как у вкладок фиши: ←/→ по кругу, Home/End, фокус идёт следом,
   в полосе одна остановка Tab (у активной tabIndex 0). ⛔ Эти клавиши
   ГАСЯТСЯ здесь: рабочий стол ловит стрелки (сосед по ряду) и Enter (записать
   черновик) с контейнера `.odop`, и без этого стрелка по вкладке увела бы
   выбор на соседний зуб. Буквы поверхностей идут дальше — к рабочему столу. */
export type Tab = 'sf' | 'dg' | 'tr' | 'nt' | 'is'

export const TABS: readonly (readonly [Tab, string])[] = [
  ['sf', 'Suprafețe'], ['dg', 'Diagnostic'], ['tr', 'Tratament'], ['nt', 'Notițe'], ['is', 'Istoric'],
]

const T = { group: 'Secțiunile dintelui' } as const

interface Props {
  tab: Tab
  onTab: (t: Tab) => void
  /** счётчик у вкладки; ноль и отсутствие — без значка */
  counts: Partial<Record<Tab, number>>
  /** основа id: вкладка `${id}-t-${k}`, панель `${id}-p` */
  id: string
}

export function PanelTabs({ tab, onTab, counts, id }: Props) {
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter') { e.stopPropagation(); return }   // Enter на вкладке — её, не запись черновика
    const i = TABS.findIndex(([k]) => k === tab)
    const n = TABS.length
    const to = e.key === 'ArrowRight' ? (i + 1) % n
      : e.key === 'ArrowLeft' ? (i + n - 1) % n
        : e.key === 'Home' ? 0 : e.key === 'End' ? n - 1 : -1
    const next = to < 0 ? undefined : TABS[to]
    // вертикальные стрелки у строки вкладок ничего не значат: ни соседа, ни прокрутки
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); e.stopPropagation(); return }
    if (!next) return
    e.preventDefault()
    e.stopPropagation()
    onTab(next[0])
    const b = e.currentTarget.children[to]
    if (b instanceof HTMLElement) b.focus()
  }
  return (
    <div className="dp-pt" role="tablist" aria-label={T.group} onKeyDown={onKey}>
      {TABS.map(([k, label]) => {
        const on = k === tab
        const c = counts[k] ?? 0
        return (
          <button key={k} type="button" role="tab" id={`${id}-t-${k}`} aria-controls={`${id}-p`} aria-selected={on}
            tabIndex={on ? 0 : -1} data-tab={k} className={`dp-pt-b${on ? ' on' : ''}`} onClick={() => onTab(k)}>
            {label}{c > 0 && <> <b className="dp-pt-n">{c}</b></>}
          </button>
        )
      })}
    </div>
  )
}
