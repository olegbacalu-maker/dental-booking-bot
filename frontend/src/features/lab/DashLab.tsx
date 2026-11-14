import { useState } from 'react'
import { useRouteLoaderData } from 'react-router'
import type { MountNode } from '../../app/doc'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { roCount } from '../../utils/plural'
import { clinicNow, clinicTz } from '../schedule/dashFx'
import { LUCRARI, type DashData, type DashRow } from './lab'

const line = (r: DashRow, tail: string) => `${r.patient} (${r.work.toLowerCase()}, ${r.lab}${tail})`

/* Закрытая плашка — удобство этого компьютера и этого человека, не данные клиники: до конца дня
   клиники и пока в ней не появилась работа, которой не было при закрытии. Хранилища нет — плашка
   просто снова видна. */
const KEY = 'dp_labdash:'

interface Closed { day: string; keys: string[] }

/** Что сейчас в плашке: опоздание, визит без работы и готовое — каждое своим ключом. */
const keysOf = (m: DashData): string[] => [
  ...m.late.map((r) => `l${r.id}`), ...m.visit.map((r) => `v${r.id}`), ...m.ready.map((r) => `r${r.id}`),
]

function readClosed(who: string): Closed | null {
  try {
    const raw = localStorage.getItem(KEY + who)
    return raw ? (JSON.parse(raw) as Closed) : null
  } catch {
    return null
  }
}

function writeClosed(who: string, c: Closed): void {
  try {
    localStorage.setItem(KEY + who, JSON.stringify(c))
  } catch {
    /* приватный режим: закрыта до перезагрузки */
  }
}

/** Закрыта ли плашка: тот же день и ничего нового против закрытого набора. */
function isClosed(c: Closed | null, day: string, keys: string[]): boolean {
  return c !== null && c.day === day && keys.every((k) => c.keys.includes(k))
}

/** Плашка панели: визит без работы, опоздания техника, готовое к выдаче. Едет конвертом живого канала —
 *  у панели одна дверь данных; пусто или нет ключа — плашки нет. */
export function DashLab({ m }: { m: DashData | null | undefined }) {
  const node = useRouteLoaderData('doc') as MountNode | undefined
  const who = node?.shell?.identity?.name ?? ''
  const [closed, setClosed] = useState<Closed | null>(() => readClosed(who))
  if (!m) return null
  if (!m.counts.late && !m.counts.ready && !m.counts.visit) return null
  const day = clinicNow(clinicTz(), new Date()).day
  const keys = keysOf(m)
  if (isClosed(closed, day, keys)) return null
  const close = () => {
    const c = { day, keys }
    writeClosed(who, c)
    setClosed(c)
  }
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
      <button type="button" className="lb-dash-x" aria-label="Închide" title="Închide până mâine — revine dacă apare o lucrare nouă"
        onClick={close}><Icon name="close" /></button>
    </div>
  )
}
