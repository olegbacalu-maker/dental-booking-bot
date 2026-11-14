import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { roCount } from '../../utils/plural'
import { LUCRARI, type DashData, type DashRow } from './lab'

const line = (r: DashRow, tail: string) => `${r.patient} (${r.work.toLowerCase()}, ${r.lab}${tail})`

/** Плашка панели: визит без работы, опоздания техника, готовое к выдаче. Едет конвертом живого канала —
 *  у панели одна дверь данных; пусто или нет ключа — плашки нет. */
export function DashLab({ m }: { m: DashData | null | undefined }) {
  if (!m) return null
  if (!m.counts.late && !m.counts.ready && !m.counts.visit) return null
  const red = m.counts.late > 0 || m.counts.visit > 0
  return (
    <div className={`lb-dash${red ? ' bad' : ''}`} role="status">
      <Icon name={red ? 'sos' : 'box'} />
      <span className="lb-dash-t">
        {m.counts.visit > 0 && (
          <span><b>Programare fără lucrare: {roCount(m.counts.visit, LUCRARI)}</b>
            {' — '}{m.visit.slice(0, 3).map((r) => line(r, r.next_appt ? `; ${r.next_appt.day === 'azi' ? 'azi' : 'mâine'} ${r.next_appt.time}` : '')).join('; ')}</span>
        )}
        {m.counts.late > 0 && (
          <span><b>Întârzie la laborator: {roCount(m.counts.late, LUCRARI)}</b>
            {' — '}{m.late.slice(0, 3).map((r) => line(r, r.days_late ? `, ${r.days_late} z.` : '')).join('; ')}</span>
        )}
        {m.counts.ready > 0 && <span>Gata de ridicat: {roCount(m.counts.ready, LUCRARI)}</span>}
      </span>
      {m.counts.visit > 0 && <AppLink className="dp-btn" href="/admin/lab?f=vizita">Programări ›</AppLink>}
      {m.counts.late > 0 && <AppLink className="dp-btn" href="/admin/lab?f=intarziate">Întârziate ›</AppLink>}
      {m.counts.ready > 0 && <AppLink className="dp-btn" href="/admin/lab?f=ridicat">De ridicat ›</AppLink>}
    </div>
  )
}
