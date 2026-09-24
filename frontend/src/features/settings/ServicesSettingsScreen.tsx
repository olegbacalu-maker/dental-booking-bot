import { useCallback, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { settings, type ServiceEntry, type ServicesData } from './settings'

const T = {
  title: 'Servicii',
  cols: { ro: 'Denumire (RO)', ru: 'Denumire (RU)', price: 'Preț', dur: 'Durată',
    color: 'Culoare', docs: 'Medici' },
  auto: 'auto',
  allDocs: 'gol = toți',
  add: '+ Adaugă serviciu',
  hintA: 'Coloana «Medici»: bifați medicii care fac serviciul; niciunul bifat = toți medicii. ',
  hintB: ' = flux urgent (fără alegerea medicului, sloturi din ziua curentă).',
  save: 'Salvează serviciile',
  remove: 'Șterge rândul',
  phRo: 'Serviciu',
  phRu: 'Услуга',
  phPrice: '500 MDL',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

const EMPTY: ServiceEntry = { id: '', ro: '', ru: '', price: '', duration: 60, color: '', urgent: false, docs: [] }

interface Props {
  navigate?: (url: string) => void
}

/** Данные экрана грузит роутер (B2.2), App.tsx › LOADS. */
export const loadServicesSettings: RouteLoad<ServicesData> = (signal) => settings.services(signal)

/**
 * Таблица услуг — те же колонки и то же тело запроса, что у старой страницы;
 * дубли подписей и всё прочее проверяет сервер (_val_services), а правки при
 * отказе не пропадают: они живут в состоянии экрана, не в перерисованной форме.
 */
export function ServicesSettingsScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<ServicesData>(navigate)
  const [rows, setRows] = useState<ServiceEntry[] | null>(null)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

  const data: ServicesData | null = state.status === 'ready' ? state.data : null
  const list = rows ?? data?.services ?? []
  const patch = (i: number, p: Partial<ServiceEntry>) =>
    setRows(list.map((r, k) => (k === i ? { ...r, ...p } : r)))
  const remove = (i: number) => setRows(list.filter((_, k) => k !== i))
  const add = () => setRows([...list, { ...EMPTY }])
  const toggleDoc = (i: number, dk: string) => {
    const r = list[i] as ServiceEntry
    patch(i, { docs: r.docs.includes(dk) ? r.docs.filter((x) => x !== dk) : [...r.docs, dk] })
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      const r = await settings.servicesSave(list)
      replace(r.data)
      setRows(r.data.services)
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
  const head = <h2><Icon name="tooth" /> {T.title}</h2>
  if (state.status === 'failed') {
    return <section className="dp-react-root">{head}<LoadFailed error={state.error} onRetry={retry} /></section>
  }

  return (
    <section className="dp-react-root" aria-busy={data === null}>
      {head}
      <form onSubmit={onSubmit}>
        <table className="set set-wide">
          <thead>
            <tr>
              <th>{T.cols.ro}</th><th>{T.cols.ru}</th><th style={{ width: 150 }}>{T.cols.price}</th>
              <th style={{ width: 90 }}>{T.cols.dur}</th><th style={{ width: 100 }}>{T.cols.color}</th>
              <th style={{ width: 40 }}><Icon name="sos" /></th><th style={{ width: 140 }}>{T.cols.docs}</th><th />
            </tr>
          </thead>
          <tbody>
            {data && list.map((s, i) => (
              <tr key={s.id || `new-${i}`}>
                <td><input type="text" value={s.ro} placeholder={T.phRo} aria-label={`${T.cols.ro} ${i + 1}`}
                  maxLength={60} disabled={saving} onChange={(e) => patch(i, { ro: e.target.value })} /></td>
                <td><input type="text" value={s.ru} placeholder={T.phRu} aria-label={`${T.cols.ru} ${i + 1}`}
                  maxLength={60} disabled={saving} onChange={(e) => patch(i, { ru: e.target.value })} /></td>
                <td><input type="text" value={s.price} placeholder={T.phPrice} aria-label={`${T.cols.price} ${i + 1}`}
                  maxLength={60} disabled={saving} onChange={(e) => patch(i, { price: e.target.value })} /></td>
                <td>
                  <select value={s.duration} aria-label={`${T.cols.dur} ${i + 1}`} disabled={saving}
                    onChange={(e) => patch(i, { duration: Number(e.target.value) })}>
                    {data.durations.map((d) => <option key={d} value={d}>{d} min</option>)}
                  </select>
                </td>
                <td>
                  <select value={s.color} aria-label={`${T.cols.color} ${i + 1}`} disabled={saving}
                    onChange={(e) => patch(i, { color: e.target.value })}>
                    <option value="">{T.auto}</option>
                    {Object.entries(data.palette).map(([k, name]) => <option key={k} value={k}>{name}</option>)}
                  </select>
                </td>
                <td style={{ textAlign: 'center' }}>
                  <input type="checkbox" checked={s.urgent} aria-label={`urgent ${i + 1}`} disabled={saving}
                    onChange={(e) => patch(i, { urgent: e.target.checked })} />
                </td>
                <td>
                  <div className="dp-svc-docs">
                    {data.doctors.map((d) => (
                      <label key={d.id}>
                        <input type="checkbox" checked={s.docs.includes(d.id)} disabled={saving}
                          onChange={() => toggleDoc(i, d.id)} />
                        {d.name}
                      </label>
                    ))}
                    {s.docs.length === 0 && <small>{T.allDocs}</small>}
                  </div>
                </td>
                <td>
                  <button type="button" className="rowdel" aria-label={`${T.remove} ${i + 1}`} disabled={saving}
                    onClick={() => remove(i)}><Icon name="close" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className="addrow" onClick={add} disabled={data === null || saving}>{T.add}</button>
        <p className="hint">{T.hintA}<Icon name="sos" />{T.hintB}</p>
        <button className="savebtn" disabled={data === null || saving}><Icon name="save" /> {T.save}</button>
      </form>
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
