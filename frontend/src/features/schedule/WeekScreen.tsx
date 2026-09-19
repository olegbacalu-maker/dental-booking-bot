import { useCallback, useState } from 'react'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { week, type WeekDay, type WeekItem } from './week'

/* Недельный календарь (C24): колонки рабочих дней, компактные чипы записей.
   Те же классы, что у старой страницы (.week, .wcol, .wh, .wb, .wchip, .nav),
   поэтому panel.css красит экран без единого нового правила.

   ⛔ Экран НЕ живой, и это не упущение. Неделя делила ключ живого раздела с
   днём (`dash`), а React-дерево внутри #live умирает при первой же подмене:
   panel.js переписывает innerHTML под смонтированным деревом. Сервер сам
   перестаёт объявлять страницу живой, когда видит в теле узел React
   (layout._shell), а здесь свежесть даёт перезагрузка по переходу — как и
   было у недели до живого протокола.
   ⛔ Дни рисуются СПИСКОМ, который прислал сервер. Никаких семи позиций и
   никакого индекса по дню недели: закрытый день исчезает, и раскладка по
   `weekday()` поставила бы субботу под воскресенье. */
const T = {
  title: 'Săptămâna',
  day: 'Zi',
  week: 'săpt.',
  today: 'Azi',
  free: '— liber —',
  counted: 'programări',
  hint: 'Click pe ziua din antet — deschide programul zilei.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

interface Props {
  /** Дата из адреса: пусто — текущая неделя. */
  date?: string
  navigate?: (url: string) => void
}

export function WeekScreen({ date = '', navigate = defaultNavigate }: Props) {
  const [at, setAt] = useState(date)
  const load = useCallback((signal: AbortSignal) => week.get(at, signal), [at])
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
  /** Переход на другую неделю: адрес меняется, чтобы F5 вернул сюда же. */
  const go = (iso: string) => {
    setAt(iso)
    try { window.history.replaceState(null, '', `/admin/week?date=${iso}`) } catch { /* jsdom */ }
  }

  return (
    <section className="dp-react-root">
      <div className="nav">
        <b>{m.span} · {m.total} {T.counted}</b>
        <a href={`/admin/week?date=${m.prev}`}
           onClick={(e) => { e.preventDefault(); go(m.prev) }}>
          <Icon name="chev-l" /> {T.week}
        </a>
        <a href="/admin/week" onClick={(e) => { e.preventDefault(); go('') }}>{T.today}</a>
        <a href={`/admin/week?date=${m.next}`}
           onClick={(e) => { e.preventDefault(); go(m.next) }}>
          {T.week} <Icon name="chev-r" />
        </a>
        <a href={`/admin?date=${m.day}`}>{T.day}</a>
        <a className="primary" href={`/admin/week?date=${m.day}`}>{T.title}</a>
      </div>
      <div className="week">
        {m.days.map((d) => <WeekColumn key={d.date} day={d} />)}
      </div>
      <p className="hint">{T.hint}</p>
    </section>
  )
}

function WeekColumn({ day }: { day: WeekDay }) {
  return (
    <div className="wcol">
      <div className={`wh${day.today ? ' tdy' : ''}`}>
        <a href={`/admin?date=${day.date}`}>{day.label} {day.dm}</a>
        <small>{day.count} {T.counted}</small>
      </div>
      <div className="wb">
        {day.items.length
          ? day.items.map((x, i) => <Chip key={x.kind === 'appt' ? x.id : `n${i}`} item={x} />)
          : <div className="dp-wfree">{T.free}</div>}
      </div>
    </div>
  )
}

function Chip({ item }: { item: WeekItem }) {
  if (item.kind === 'note') {
    return (
      <div className="wchip gnote dp-wnote">
        <Icon name="note" /> {item.time} {item.text_cut}
      </div>
    )
  }
  return (
    <div
      className={`wchip${item.noshow ? ' noshow' : ''}`}
      style={{ background: item.bg, borderLeft: `5px solid ${item.bar}` }}
    >
      <b>{item.time}</b> {item.name}
      <small>{item.service}</small>
    </div>
  )
}
