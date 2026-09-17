import { Icon } from '../../components/Icon'
import type { TodayRow, WeekCell } from './doctors'

const T = {
  next7: 'Următoarele 7 zile',
  next7sub: '· click = ziua completă',
  today: 'Astăzi, ',
  grid: 'grila zilei',
  none: '— nicio programare —',
  cols: ['#', 'Ora', 'Pacient', 'Telefon', 'Serviciu', 'Status'],
} as const

/** ISO-дата (гггг-мм-дд) → дд.мм.гггг, как в заголовке старой таблицы дня. */
function dmy(iso: string): string {
  const [y, m, d] = iso.split('-')
  return `${d}.${m}.${y}`
}

interface Props {
  dk: string
  week: WeekCell[]
  today: TodayRow[]
}

/**
 * Ближайшие 7 дней и сегодняшний список врача. Список здесь — таблица со
 * ссылками на фишу пациента; действия со статусом и карточка визита остаются
 * у журнала и переедут вместе с ним (группа 5).
 */
export function DoctorWeek({ dk, week, today }: Props) {
  const first = week[0]
  const dayUrl = (date: string) => `/admin/doctor/${encodeURIComponent(dk)}?date=${date}`
  return (
    <>
      <div className="fcard">
        <h3>{T.next7} <small>{T.next7sub}</small></h3>
        <div style={{ display: 'flex', gap: 6 }}>
          {week.map((c) => (
            <a
              key={c.date}
              href={dayUrl(c.date)}
              className="dp-daycell"
              style={{ background: c.open ? (c.count ? 'var(--teal-soft)' : 'var(--bg)') : 'var(--line2)' }}
            >
              <div className="dp-daycell-l">{c.label} {c.dm}</div>
              <div className="dp-daycell-n">{c.open ? c.count : '—'}</div>
            </a>
          ))}
        </div>
      </div>
      <div className="fcard" style={{ paddingTop: 4 }}>
        <h2>
          {T.today}{first ? dmy(first.date) : ''}{' '}
          {first && (
            <small style={{ fontSize: 12, fontWeight: 400 }}>
              <a href={dayUrl(first.date)}>{T.grid} <Icon name="out" /></a>
            </small>
          )}
        </h2>
        <div style={{ overflowX: 'auto' }}>
          <table className="list">
            <thead>
              <tr>{T.cols.map((c) => <th key={c}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {today.length === 0 ? (
                <tr><td colSpan={T.cols.length} style={{ color: 'var(--text3)' }}>{T.none}</td></tr>
              ) : (
                today.map((r) => (
                  <tr key={r.id} className={r.status}>
                    <td>{r.id}</td>
                    <td>{r.time}</td>
                    <td>
                      {r.patient_id !== null && !r.note ? (
                        <a className="plink" href={`/admin/patient/${r.patient_id}`}>{r.patient}</a>
                      ) : (
                        r.patient
                      )}
                    </td>
                    <td>{r.phone}</td>
                    <td>
                      {r.service}
                      {r.comment && <><br /><small className="dp-comment">{r.comment}</small></>}
                    </td>
                    <td><span className={`stat s-${r.status}`}>{r.status_label}</span></td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
