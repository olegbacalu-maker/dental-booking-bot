import { useCallback, useState } from 'react'
import { useSearchParams } from 'react-router'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { api } from '../../services/api'
import { roCount } from '../../utils/plural'
import { useLabHost } from './host'
import { COMENZI, isOpen, labApi, money, type Filter, type ListData } from './lab'
import { Appt, Due, RowActs, StatusPill, teethText, UrgentTag } from './parts'

const FILTERS: [Filter, string][] = [
  ['lucru', 'În lucru'], ['intarziate', 'Întârziate'], ['vizita', 'Programare fără lucrare'], ['ridicat', 'De ridicat'],
  ['primite', 'Primite / la probă'], ['finalizate', 'Finalizate'], ['anulate', 'Anulate'], ['toate', 'Toate'],
]
const isFilter = (s: string | null): s is Filter => FILTERS.some(([k]) => k === s)
const RED: Filter[] = ['intarziate', 'vizita']

/** Общий список заказов клиники: что у техника, что опаздывает, что забирать, у кого визит без работы. */
export function LabListScreen({ navigate = defaultNavigate }: { navigate?: (url: string) => void }) {
  const [q, setQ] = useSearchParams()
  const qf = q.get('f')
  const f: Filter = isFilter(qf) ? qf : 'lucru'
  const labF = Number(q.get('lab')) || 0
  const find = q.get('q') ?? ''
  const [typed, setTyped] = useState(find)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [picking, setPicking] = useState(false)
  const load = useCallback((signal: AbortSignal) => labApi.list({ f, lab: labF, q: find }, signal), [f, labF, find])
  const { state, retry } = useLoad<ListData>(load, navigate)
  const host = useLabHost(retry, (text, tone) => setToast({ text, tone }), navigate)
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(q)
    if (v) p.set(k, v)
    else p.delete(k)
    setQ(p, { replace: true })
  }

  if (state.status === 'leaving') return null
  if (state.status === 'failed') return <section className="dp-react-root"><LoadFailed error={state.error} onRetry={retry} /></section>
  const data = state.status === 'ready' ? state.data : null
  const rows = data?.orders ?? []
  const withMoney = data?.can.money ?? false
  const sum = rows.reduce((s, o) => s + (o.total_bani ?? 0), 0)
  const empty = data !== null && data.counts.toate === 0

  return (
    <section className="dp-react-root rg lb" aria-busy={state.status === 'loading' || undefined}>
      <div className="fcard rg-head">
        <div className="rg-tabs" role="tablist" aria-label="Filtru">
          {FILTERS.filter(([k]) => k === f || k === 'lucru' || k === 'toate' || (data?.counts[k] ?? 0) > 0).map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={f === k}
              className={`rg-tab${f === k ? ' on' : ''}${RED.includes(k) && data?.counts[k] ? ' lb-late' : ''}`}
              onClick={() => set('f', k === 'lucru' ? '' : k)}>
              {label} <span className="rg-n">{data?.counts[k] ?? '…'}</span>
            </button>
          ))}
        </div>
        <form className="rg-tools" role="search" onSubmit={(e) => { e.preventDefault(); set('q', typed.trim()) }}>
          <input className="dp-fld lb-find" placeholder="Pacient, nr. fișei, lucrare" value={typed} onChange={(e) => setTyped(e.target.value)}
            onBlur={() => { if (typed.trim() !== find) set('q', typed.trim()) }} aria-label="Caută" />
          {(data?.labs.length ?? 0) > 1 && (
            <select className="dp-sel" value={labF} onChange={(e) => set('lab', e.target.value === '0' ? '' : e.target.value)} aria-label="Laborator">
              <option value={0}>Toate laboratoarele</option>
              {data!.labs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          )}
          <button type="button" className="rg-btn pri" onClick={() => setPicking(true)}><Icon name="plus" /> Comandă nouă</button>
        </form>
      </div>

      {empty ? (
        <div className="fcard rg-empty">
          <span className="rg-empty-ico"><Icon name="box" /></span>
          <b>Încă nu e nicio comandă la laborator</b>
          <p className="hint">Comanda se face din fișa pacientului, de la poziția din plan (coroană, punte, proteză, alignere):
            dinții, lucrarea și medicul se completează singure, iar fișa de comandă se tipărește pentru tehnician.
            Aici se vede apoi tot ce e la laborator, ce întârzie și ce e de ridicat.</p>
          {data.labs.length === 0 && (data.can.labs
            ? <p className="hint">Laboratoarele cu care lucrați se adaugă în <AppLink href="/admin/settings/lab">Setări › Laboratoare</AppLink>
                {' '}— sau direct în prima comandă.</p>
            : <p className="hint">Laboratoarele le adaugă recepția în Setări › Laboratoare.</p>)}
          <button type="button" className="rg-btn pri" onClick={() => setPicking(true)}><Icon name="plus" /> Prima comandă</button>
        </div>
      ) : (
        <div className="fcard rg-body">
          <div className="rg-scroll">
            <table className="rg-tbl lb-tbl">
              <thead>
                <tr><th>Nr.</th><th>Pacient</th><th>Dinți</th><th>Lucrarea</th><th>Laborator</th><th>Termen</th>
                  <th>Programare</th><th>Stare</th>{withMoney && <th className="num">Preț lab.</th>}<th /></tr>
              </thead>
              <tbody>
                {rows.map((o) => (
                  <tr key={o.id} className={`${o.late ? 'lb-late-r' : o.visit_wait ? 'lb-warn-r' : ''}${isOpen(o) ? '' : ' lb-done-r'}`} data-st={o.status}>
                    <td className="num">{o.nr}</td>
                    <td className="lb-pat"><AppLink href={`/admin/patient/${o.pid}?tab=plan`}><b>{o.patient}</b></AppLink><small>{o.doctor || '—'}</small></td>
                    <td className="num">{teethText(o.teeth)}</td>
                    <td>{o.work}{o.urgent && <UrgentTag />}</td>
                    <td>{o.lab}</td>
                    <td><Due o={o} /></td>
                    <td><Appt a={isOpen(o) ? o.next_appt : null} warn={o.visit_wait} /></td>
                    <td><StatusPill o={o} /></td>
                    {withMoney && <td className="num">{o.total_bani != null ? money(o.total_bani) : '—'}</td>}
                    <td className="lb-act-c"><RowActs o={o} host={host} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data && rows.length === 0 && <p className="hint rg-none">Nimic în acest filtru.</p>}
          {rows.length > 0 && (
            <p className="hint rg-foot"><Icon name="info" /> {roCount(rows.length, COMENZI)}
              {withMoney && sum ? ` · preț laborator ${money(sum)} MDL` : ''}. Întârziatele sunt primele.</p>
          )}
        </div>
      )}
      {picking && <PatientPick onClose={() => setPicking(false)} onPick={(pid) => { setPicking(false); host.create(pid) }} />}
      {host.node}
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={() => setToast(null)} />}
    </section>
  )
}

interface Row { id: number; name: string; phone: string }

/** «Comandă nouă» из списка: сначала пациент (поиск картотеки), позиции его плана — уже в окне заказа. */
function PatientPick({ onClose, onPick }: { onClose: () => void; onPick: (pid: number) => void }) {
  const [find, setFind] = useState('')
  const [rows, setRows] = useState<Row[]>([])
  const search = async (s: string) => {
    setFind(s)
    if (s.trim().length < 2) { setRows([]); return }
    try {
      const r = await api.get<{ rows: Row[] }>(`/patients?q=${encodeURIComponent(s.trim())}`)
      setRows(r.data.rows)
    } catch { setRows([]) }
  }
  return (
    <div className="lb-pickpane fcard" role="dialog" aria-label="Comandă nouă — alegeți pacientul">
      <div className="rg-card-h"><b>Pentru ce pacient?</b>
        <button type="button" className="rg-ib" onClick={onClose} aria-label="Închide"><Icon name="close" /></button></div>
      <input className="dp-fld" autoFocus placeholder="Numele sau telefonul pacientului" value={find}
        onChange={(e) => { void search(e.target.value) }} aria-label="Pacient" />
      <div className="rg-chips">
        {rows.slice(0, 12).map((r) => (
          <button key={r.id} type="button" className="rg-chip" onClick={() => onPick(r.id)}>{r.name} <small>{r.phone}</small></button>
        ))}
      </div>
      {find.trim().length >= 2 && rows.length === 0 && <small className="hint">Niciun pacient găsit.</small>}
    </div>
  )
}
