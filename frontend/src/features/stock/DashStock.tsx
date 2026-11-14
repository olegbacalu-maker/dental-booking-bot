import { useState } from 'react'
import { useRouteLoaderData } from 'react-router'
import type { MountNode } from '../../app/doc'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { roCount } from '../../utils/plural'
import { clinicNow, clinicTz } from '../schedule/dashFx'
import { MATERIALE, type DashData } from './stock'

/* Закрытая плашка — удобство этого компьютера и этого человека, не данные клиники: до конца дня клиники и пока
   не появился материал, которого не было при закрытии (тот же приём, что у плашки лаборатории). */
const KEY = 'dp_stockdash:'

interface Closed { day: string; keys: string[] }

const keysOf = (m: DashData): string[] => [...m.low_items.map((r) => `l${r.id}`), ...m.exp_items.map((r) => `e${r.id}`),
  `n${m.low}:${m.soon + m.expired}`]

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

/** Плашка панели: что ниже порога (заказанное не прячется) и что скоро истечёт. Едет в конверте живого канала;
 *  `null` — врачу и пустому складу: плашки нет. */
export function DashStock({ m }: { m: DashData | null | undefined }) {
  const node = useRouteLoaderData('doc') as MountNode | undefined
  const who = node?.shell?.identity?.name ?? ''
  const [closed, setClosed] = useState<Closed | null>(() => readClosed(who))
  if (!m) return null
  const exp = m.soon + m.expired
  if (!m.low && !exp) return null
  const day = clinicNow(clinicTz(), new Date()).day
  const keys = keysOf(m)
  if (closed && closed.day === day && keys.every((k) => closed.keys.includes(k))) return null
  const close = () => {
    const c = { day, keys }
    writeClosed(who, c)
    setClosed(c)
  }
  const extra = [m.neg ? `${m.neg} pe minus` : '', m.ordered ? `din care comandate: ${m.ordered}` : ''].filter(Boolean).join(' · ')
  const names = [...m.low_items.map((r) => r.name), ...m.exp_items.filter((r) => !m.low_items.some((l) => l.id === r.id)).map((r) => r.name)].slice(0, 3)
  return (
    <div className="st-dash" role="status">
      <Icon name="box" />
      <span className="st-dash-t">
        {m.low > 0 && <b>{roCount(m.low, MATERIALE)} sub prag</b>}
        {extra && <> ({extra})</>}
        {m.low > 0 && exp > 0 && ' · '}
        {exp > 0 && <b>{m.expired ? `${exp} expiră sau au expirat` : `${exp} expiră în curând`}</b>}
        {names.length > 0 && <small> — {names.join(', ')}{m.low + exp > names.length ? '…' : ''}</small>}
      </span>
      {m.low > 0 && <AppLink className="dp-btn" href="/admin/stoc?v=cumparat">De cumpărat ›</AppLink>}
      {exp > 0 && <AppLink className="dp-btn" href="/admin/stoc?f=exp">Expiră ›</AppLink>}
      <button type="button" className="st-dash-x" aria-label="Închide" title="Închide până mâine — revine dacă apare un material nou"
        onClick={close}><Icon name="close" /></button>
    </div>
  )
}
