import { useNavigate } from 'react-router'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { defaultNavigate } from '../../hooks/useLoad'
import { queryParam, useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { week, type WeekDay, type WeekItem, type WeekModel } from './week'

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
  navigate?: (url: string) => void
}

/**
 * Данные грузит роутер (B2.2), и ДАТУ он берёт из адреса (B2.3): владелец
 * «какая неделя» — `?date=` в адресе, и больше никто. Пусто — текущая
 * неделя, её день считает сервер в поясе клиники, а не браузер.
 */
export const loadWeek: RouteLoad<WeekModel> = (signal, _p, q) => week.get(queryParam(q, 'date'), signal)

export function WeekScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry } = useRouteLoad<WeekModel>(navigate)
  const to = useNavigate()

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
  /** Переход на другую неделю — через РОУТЕР: адрес меняется, загрузчик читает
   *  уже его, и F5 на этом адресе вернёт ту же неделю. `replace`, как и было:
   *  листание недель не копит шаги «Назад». Пока ответа нет, на экране прежняя
   *  неделя — так было и до роутера (экран только читает). */
  const go = (iso: string) => {
    void to(iso ? `/admin/week?date=${iso}` : '/admin/week', { replace: true })
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
        {/* Вкладка дня — переход без перезагрузки (B4.1): сайдбар и шапка на месте. */}
        <AppLink href={`/admin?date=${m.day}`}>{T.day}</AppLink>
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
