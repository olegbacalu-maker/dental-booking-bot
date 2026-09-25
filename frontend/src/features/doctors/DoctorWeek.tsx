import { Icon } from '../../components/Icon'
import { AppLink } from '../../components/AppLink'
import type { StatusAction, TodayRow, WeekCell } from './doctors'

const T = {
  next7: 'Următoarele 7 zile',
  next7sub: '· click = ziua completă',
  today: 'Astăzi, ',
  grid: 'grila zilei',
  none: '— nicio programare —',
  cols: ['#', 'Ora', 'Pacient', 'Telefon', 'Serviciu', 'Status', 'Acțiuni'],
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
  actions: Record<string, StatusAction[]>
  noteActions: Record<string, StatusAction[]>
  busy: boolean
  onStatus: (id: number, to: string) => void
}

/**
 * Ближайшие 7 дней и сегодняшний список врача.
 *
 * ⭐ Кнопки исхода (C14+) берутся С СЕРВЕРА — `actions` для записи,
 * `note_actions` для заметки стойки, — и это та же матрица, что у списка дня
 * (`core.visits.status_actions`). Своя копия «какие кнопки у завершённого
 * визита» разошлась бы с журналом молча: закрытая запись теряла бы кнопку
 * возврата в одном месте и сохраняла в другом.
 * ⛔ Карточки визита здесь по-прежнему нет: она живёт в журнале, и её перенос
 * сюда был бы вторым экраном визита, а не кнопкой.
 */
export function DoctorWeek({ dk, week, today, actions, noteActions, busy, onStatus }: Props) {
  const first = week[0]
  const dayUrl = (date: string) => `/admin/doctor/${encodeURIComponent(dk)}?date=${date}`
  return (
    <>
      <div className="fcard">
        <h3>{T.next7} <small>{T.next7sub}</small></h3>
        <div style={{ display: 'flex', gap: 6 }}>
          {week.map((c) => (
            <AppLink
              key={c.date}
              href={dayUrl(c.date)}
              className="dp-daycell"
              style={{ background: c.open ? (c.count ? 'var(--teal-soft)' : 'var(--bg)') : 'var(--line2)' }}
            >
              <div className="dp-daycell-l">{c.label} {c.dm}</div>
              <div className="dp-daycell-n">{c.open ? c.count : '—'}</div>
            </AppLink>
          ))}
        </div>
      </div>
      <div className="fcard" style={{ paddingTop: 4 }}>
        <h2>
          {T.today}{first ? dmy(first.date) : ''}{' '}
          {first && (
            <small style={{ fontSize: 12, fontWeight: 400 }}>
              <AppLink href={dayUrl(first.date)}>{T.grid} <Icon name="out" /></AppLink>
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
                        <AppLink className="plink" href={`/admin/patient/${r.patient_id}`}>{r.patient}</AppLink>
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
                    <td>
                      {((r.note ? noteActions : actions)[r.status] ?? []).map((a) => (
                        <form key={a.to} className="act" onSubmit={(e) => {
                          e.preventDefault()
                          if (a.confirm && !window.confirm(a.confirm)) return
                          onStatus(r.id, a.to)
                        }}>
                          <button className={a.cls} disabled={busy}>
                            {a.cls === 'b-reopen' ? <><Icon name="undo" /> </> : null}{a.label}
                          </button>
                        </form>
                      ))}
                    </td>
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
