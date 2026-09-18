import { useCallback, useState } from 'react'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { DayGrid } from './DayGrid'
import { day } from './day'

/* День журнала (C25.5a): «Toți medicii» и день одного врача — один экран,
   разница только в параметре `doctor`. Сетку строит `DayGrid` на классах
   panel.css; данные — GET /api/schedule/day.

   ⛔ Экран НЕ живой, как и неделя: React-дерево внутри #live умирает при
   первой подмене. Сервер сам перестаёт объявлять страницу живой, увидев узел
   (layout._shell), а свежесть здесь даёт переход по дате.
   ⚠️ Пока только чтение: запись, модалки и перетаскивание — C25.5b. Всё, что
   меняет данные, ведёт в старую страницу того же дня, а не изображает кнопку,
   которая ничего не делает. */
const T = {
  prevDay: 'zi',
  today: 'Azi',
  all: 'Toți medicii',
  panel: 'Panou',
  legacy: 'Varianta clasică',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

interface Props {
  /** Дата из адреса; пусто — сегодня. */
  date?: string
  /** Врач: пусто — все. */
  doctor?: string
  navigate?: (url: string) => void
}

function shift(iso: string, days: number): string {
  const d = iso ? new Date(`${iso}T12:00:00`) : new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

export function DayScreen({ date = '', doctor = '', navigate = defaultNavigate }: Props) {
  const [at, setAt] = useState(date)
  const load = useCallback((signal: AbortSignal) => day.get(at, doctor, signal),
    [at, doctor])
  const { state, retry } = useLoad(load, navigate)

  if (state.status === 'leaving') return null
  if (state.status === 'failed') {
    return (
      <section className="dp-react-root">
        <LoadFailed error={state.error} onRetry={retry} text={T.offline} />
      </section>
    )
  }
  if (state.status === 'loading') {
    return <section className="dp-react-root" aria-busy="true"><div className="fcard" /></section>
  }

  const m = state.data
  const base = doctor ? `/admin/doctor/${doctor}` : '/admin/all'
  const go = (iso: string) => {
    setAt(iso)
    try { window.history.replaceState(null, '', `${base}?date=${iso}`) } catch { /* jsdom */ }
  }

  return (
    <section className="dp-react-root">
      <div className="nav">
        <b>{m.date}</b>
        <a href={`${base}?date=${shift(m.date, -1)}`}
           onClick={(e) => { e.preventDefault(); go(shift(m.date, -1)) }}>
          <Icon name="chev-l" /> {T.prevDay}
        </a>
        <a href={base} onClick={(e) => { e.preventDefault(); go('') }}>{T.today}</a>
        <a href={`${base}?date=${shift(m.date, 1)}`}
           onClick={(e) => { e.preventDefault(); go(shift(m.date, 1)) }}>
          {T.prevDay} <Icon name="chev-r" />
        </a>
        <a href={`/admin?date=${m.date}`}><Icon name="home" /> {T.panel}</a>
        {doctor
          ? <a href={`/admin/all?date=${m.date}`}><Icon name="clipboard" /> {T.all}</a>
          : null}
        <a className="primary" href={`${base}?date=${m.date}&ui=legacy`}>{T.legacy}</a>
      </div>
      <DayGrid model={m} legacy={`${base}?date=${m.date}&ui=legacy`} />
    </section>
  )
}
