import { useCallback, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { asApiError } from '../../services/api'
import { settings, type DayHours, type HoursData } from './settings'

const T = {
  title: 'Program de lucru',
  cols: ['Ziua', 'Închis', 'De la', 'Până la', 'Pauză de la', 'Pauză până la'],
  closed: 'închis',
  hint:
    'Pauza (ex. prânz 13:00–14:00) dispare din calendarul zilei și din registru. ' +
    '«—» = fără pauză. Medicul își poate îngusta orele în fișa lui, dar nu le poate lărgi ' +
    'peste programul clinicii.',
  save: 'Salvează programul',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

/** Строка редактора: как у старой таблицы, закрытый день помнит 9–18. */
interface Row {
  closed: boolean
  f: number
  t: number
  bf: number | null
  bt: number | null
}

function rowsOf(d: HoursData): Record<string, Row> {
  const out: Record<string, Row> = {}
  for (const { key } of d.days) {
    const h = d.hours[key] ?? null
    out[key] = h === null
      ? { closed: true, f: 9, t: 18, bf: null, bt: null }
      : { closed: false, f: h[0], t: h[1], bf: h.length === 4 ? h[2] : null, bt: h.length === 4 ? h[3] : null }
  }
  return out
}

/** Тот же payload, что собирал скрипт старой страницы: пауза только когда заданы оба края. */
function payloadOf(rows: Record<string, Row>): Record<string, DayHours> {
  const out: Record<string, DayHours> = {}
  for (const [k, r] of Object.entries(rows)) {
    if (r.closed) out[k] = null
    else if (r.bf !== null && r.bt !== null) out[k] = [r.f, r.t, r.bf, r.bt]
    else out[k] = [r.f, r.t]
  }
  return out
}

function range(from: number, to: number): number[] {
  const out: number[] = []
  for (let h = from; h <= to; h += 1) out.push(h)
  return out
}

interface Props {
  navigate?: (url: string) => void
}

export function HoursSettingsScreen({ navigate = defaultNavigate }: Props) {
  const load = useCallback((signal: AbortSignal) => settings.hours(signal), [])
  const { state, retry, replace, leaveIfSignedOut } = useLoad(load, navigate)
  const [rows, setRows] = useState<Record<string, Row> | null>(null)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

  const data = state.status === 'ready' ? state.data : null
  const table = rows ?? (data ? rowsOf(data) : null)
  const set = (key: string, patch: Partial<Row>) =>
    setRows({ ...(table ?? {}), [key]: { ...(table?.[key] as Row), ...patch } })

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!table) return
    setSaving(true)
    try {
      const r = await settings.hoursSave(payloadOf(table))
      replace(r.data)
      setRows(rowsOf(r.data))
      setToast({ tone: r.tone, text: r.text })
    } catch (err) {
      const apiErr = asApiError(err)
      if (leaveIfSignedOut(apiErr)) return
      setToast({ tone: 'err', text: apiErr.text || T.offline })
    } finally {
      setSaving(false)
    }
  }

  if (state.status === 'leaving') return null
  const head = <h2><Icon name="clock" /> {T.title}</h2>
  if (state.status === 'failed') {
    return <section className="dp-react-root">{head}<LoadFailed error={state.error} onRetry={retry} /></section>
  }

  const min = data?.range.min ?? 7
  const max = data?.range.max ?? 21
  const opt = (h: number) => <option key={h} value={h}>{h}:00</option>

  return (
    <section className="dp-react-root" aria-busy={data === null}>
      {head}
      <form onSubmit={onSubmit}>
        <table className="set">
          <thead><tr>{T.cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {data && table && data.days.map(({ key, label }) => {
              const r = table[key] as Row
              const dis = saving || r.closed
              return (
                <tr key={key}>
                  <td>{label}</td>
                  <td>
                    <label>
                      <input type="checkbox" checked={r.closed} disabled={saving}
                        onChange={(e) => set(key, { closed: e.target.checked })} />{' '}
                      {T.closed}
                    </label>
                  </td>
                  <td>
                    <select aria-label={`${label}: ${T.cols[2]}`} value={r.f} disabled={dis}
                      onChange={(e) => set(key, { f: Number(e.target.value) })}>
                      {range(min, max).map(opt)}
                    </select>
                  </td>
                  <td>
                    <select aria-label={`${label}: ${T.cols[3]}`} value={r.t} disabled={dis}
                      onChange={(e) => set(key, { t: Number(e.target.value) })}>
                      {range(min + 1, max).map(opt)}
                    </select>
                  </td>
                  <td>
                    <select aria-label={`${label}: ${T.cols[4]}`} value={r.bf ?? ''} disabled={dis}
                      onChange={(e) => set(key, { bf: e.target.value === '' ? null : Number(e.target.value) })}>
                      <option value="">—</option>
                      {range(min, max).map(opt)}
                    </select>
                  </td>
                  <td>
                    <select aria-label={`${label}: ${T.cols[5]}`} value={r.bt ?? ''} disabled={dis}
                      onChange={(e) => set(key, { bt: e.target.value === '' ? null : Number(e.target.value) })}>
                      <option value="">—</option>
                      {range(min, max).map(opt)}
                    </select>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <p className="hint">{T.hint}</p>
        <button className="savebtn" disabled={saving || data === null}>
          <Icon name="save" /> {T.save}
        </button>
      </form>
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
