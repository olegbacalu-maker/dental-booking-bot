import { useCallback, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { asApiError, type ApiResult } from '../../services/api'
import { roCount } from '../../utils/plural'
import { COMENZI, labApi, WEEKDAYS, type Lab, type SettingsData } from './lab'

type Draft = { id?: number; name: string; phone: string; email: string; contact: string; days: string; workdays: string; active: boolean; idno: string }

const blank: Draft = { name: '', phone: '', email: '', contact: '', days: '7', workdays: '12345', active: true, idno: '' }
const draftOf = (l: Lab): Draft => ({ id: l.id, name: l.name, phone: l.phone, email: l.email, contact: l.contact, days: String(l.days),
  workdays: l.workdays, active: l.active, idno: l.data.idno ?? '' })
const wdText = (w: string) => (w === '12345' ? 'luni–vineri' : WEEKDAYS.filter(([k]) => w.includes(k)).map(([, n]) => n).join(', ') || '—')

/** Setări › Laboratoare: каталог, из которого окно заказа делает кнопки и считает срок по рабочим дням. */
export function LabSettingsScreen({ navigate = defaultNavigate }: { navigate?: (url: string) => void }) {
  const load = useCallback((signal: AbortSignal) => labApi.settings(signal), [])
  const { state, retry } = useLoad<SettingsData>(load, navigate)
  const [edit, setEdit] = useState<Draft | null>(null)
  const [field, setField] = useState('')
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)

  if (state.status === 'leaving') return null
  if (state.status === 'failed') return <section className="dp-react-root"><LoadFailed error={state.error} onRetry={retry} /></section>
  const data = state.status === 'ready' ? state.data : null
  const labs = data?.labs ?? []
  const ed = edit ?? (data && labs.length === 0 ? blank : null)

  async function run(f: () => Promise<ApiResult<unknown>>, after?: () => void): Promise<void> {
    setBusy(true)
    setField('')
    try {
      const r = await f()
      if (r.text) setToast({ tone: 'ok', text: r.text })
      after?.()
      retry()
    } catch (e) {
      const a = asApiError(e)
      setField(a.field ?? '')
      setToast({ tone: 'err', text: a.text || 'Nu s-a salvat.' })
    } finally {
      setBusy(false)
    }
  }
  const save = (d: Draft) => run(() => labApi.saveLab({
    ...(d.id ? { id: d.id } : {}), name: d.name.trim(), phone: d.phone.trim(), email: d.email.trim(), contact: d.contact.trim(),
    days: Math.max(1, Number(d.days) || 7), workdays: d.workdays, active: d.active, data: { idno: d.idno.trim() },
  }), () => setEdit(null))
  const drop = async (d: Draft) => {
    if (!d.id || !await ask({ text: `Ștergeți laboratorul „${d.name}"?`, danger: true })) return
    await run(() => labApi.dropLab(d.id!), () => setEdit(null))
  }

  return (
    <section className="dp-react-root rg rg-set lb" aria-busy={state.status === 'loading' || undefined}>
      <p className="rg-crumb"><AppLink href="/admin/settings">Setări</AppLink> › Laboratoare</p>
      <div className="fcard rg-head">
        <div className="rg-ttl"><b>Laboratoare de tehnică dentară</b>
          <small>Din această listă se alege laboratorul în comandă; termenul se socotește în zilele lucrătoare ale laboratorului.</small></div>
        <AppLink className="rg-btn" href="/admin/lab"><Icon name="box" /> Comenzi laborator</AppLink>
      </div>
      <div className="rg-set-grid">
        <div className="fcard rg-card wide lb-labs">
          <div className="rg-card-h"><b>Laboratoare</b>
            <small>{labs.length ? `${labs.filter((l) => l.active).length} active` : 'lista e goală'}</small>
            <button type="button" className="rg-btn sm" disabled={busy} onClick={() => setEdit(blank)}><Icon name="plus" /> Adaugă</button></div>
          {data && labs.length === 0 && (
            <p className="hint rg-lead">Adăugați laboratoarele cu care lucrează clinica. Se poate și din prima comandă — „Alt laborator" —
              laboratorul ajunge atunci aici singur.</p>
          )}
          {ed && !ed.id && <Editor f={ed} set={setEdit} busy={busy} field={field} save={save} drop={drop} />}
          {labs.map((l) => (ed?.id === l.id
            ? <Editor key={l.id} f={ed} set={setEdit} busy={busy} field={field} save={save} drop={drop} used={l.orders} />
            : (
              <div key={l.id} className={`rg-item${l.active ? '' : ' off'}`}>
                <div><b>{l.name}</b>
                  <small>{[l.phone, l.email, l.contact].filter(Boolean).join(' · ') || 'fără date de contact'}</small>
                  {!l.active && <small>nu mai apare în comenzi noi</small>}</div>
                <div className="rg-tags"><span className="chip mute">{l.days} zile lucrătoare · {wdText(l.workdays)}</span>
                  {l.orders > 0 && <span className="chip info">{roCount(l.orders, COMENZI)}{l.open ? `, ${l.open} în lucru` : ''}</span>}</div>
                <button type="button" className="rg-ib" aria-label={`Editează ${l.name}`} disabled={busy} onClick={() => setEdit(draftOf(l))}><Icon name="pen" /></button>
              </div>
            )))}
        </div>
        {data?.can.settings && (
          <>
            <div className="fcard rg-card">
              <div className="rg-card-h"><b>Fișa de comandă</b><small>ce află laboratorul despre pacient</small></div>
              <div className="rg-chips">
                {([['name', 'Numele pacientului'], ['fisa', 'Doar numărul fișei']] as const).map(([v, label]) => (
                  <button key={v} type="button" className={`rg-chip${data.prefs.who === v ? ' on' : ''}`} aria-pressed={data.prefs.who === v} disabled={busy}
                    onClick={() => { void run(() => labApi.prefs({ who: v })) }}>{label}</button>
                ))}
              </div>
              <p className="hint dp-m0">Restul — dinții, lucrările, materialul, culoarea, termenul și medicul. Anamneza, IDNP, telefonul și prețul nu se tipăresc.</p>
            </div>
            <div className="fcard rg-card">
              <div className="rg-card-h"><b>„Întârziat"</b><small>ce se socotește întârziere</small></div>
              <label className="rg-check"><input type="checkbox" checked={data.prefs.late_gata} disabled={busy}
                onChange={(e) => { void run(() => labApi.prefs({ late_gata: e.target.checked })) }} />
                Și lucrarea gata la laborator, dar neridicată după termen</label>
              <p className="hint dp-m0">Implicit — doar lucrarea care n-a venit de la laborator până la termen.</p>
            </div>
          </>
        )}
      </div>
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={() => setToast(null)} />}
    </section>
  )
}

function Editor({ f, set, busy, field, save, drop, used = 0 }: {
  f: Draft; set: (d: Draft | null) => void; busy: boolean; field: string
  save: (d: Draft) => Promise<void>; drop: (d: Draft) => Promise<void>; used?: number
}) {
  const up = (p: Partial<Draft>) => set({ ...f, ...p })
  const bad = (k: string) => (field === k ? ' bad' : '')
  const flip = (k: string) => up({ workdays: (f.workdays.includes(k) ? f.workdays.replace(k, '') : f.workdays + k).split('').sort().join('') })
  return (
    <div className="rg-edit">
      <div className="rg-edit-g">
        <label className="rg-f wide"><span className="rg-fl">Denumirea</span>
          <input className={`dp-fld${bad('name')}`} autoFocus value={f.name} maxLength={120} placeholder="ex. Dental Lab Prim" onChange={(e) => up({ name: e.target.value })} /></label>
        <label className="rg-f"><span className="rg-fl">Telefon</span><input className="dp-fld" value={f.phone} maxLength={30} onChange={(e) => up({ phone: e.target.value })} /></label>
        <label className="rg-f"><span className="rg-fl">E-mail</span><input className={`dp-fld${bad('email')}`} value={f.email} maxLength={80} onChange={(e) => up({ email: e.target.value })} /></label>
        <label className="rg-f"><span className="rg-fl">Persoana de contact</span><input className="dp-fld" value={f.contact} maxLength={60} onChange={(e) => up({ contact: e.target.value })} /></label>
        <label className="rg-f"><span className="rg-fl">IDNO (opțional)</span>
          <input className={`dp-fld${bad('idno')}`} inputMode="numeric" value={f.idno} onChange={(e) => up({ idno: e.target.value.replace(/\D/g, '').slice(0, 13) })} /></label>
        <label className="rg-f"><span className="rg-fl">Termen obișnuit, zile lucrătoare</span>
          <input className={`dp-fld${bad('days')}`} inputMode="numeric" value={f.days} onChange={(e) => up({ days: e.target.value.replace(/\D/g, '').slice(0, 2) })} /></label>
        <div className={`rg-f wide${bad('workdays')}`}><span className="rg-fl">Zilele lucrătoare ale laboratorului</span>
          <div className="rg-chips">
            {WEEKDAYS.map(([k, n]) => (
              <button key={k} type="button" className={`rg-chip sm${f.workdays.includes(k) ? ' on' : ''}`} aria-pressed={f.workdays.includes(k)} onClick={() => flip(k)}>{n}</button>
            ))}
          </div>
        </div>
      </div>
      <div className="rg-card-f">
        {f.id && <label className="rg-check"><input type="checkbox" checked={f.active} onChange={(e) => up({ active: e.target.checked })} /> Activ</label>}
        {f.id && used === 0 && <button type="button" className="rg-btn" disabled={busy} onClick={() => { void drop(f) }}><Icon name="trash" /> Șterge</button>}
        <button type="button" className="rg-btn" disabled={busy} onClick={() => set(null)}>Renunță</button>
        <button type="button" className="dp-btn pri" disabled={busy || !f.name.trim() || !f.workdays} onClick={() => { void save(f) }}><Icon name="save" /> Salvează</button>
      </div>
      {f.id && used > 0 && <small className="hint">Are {roCount(used, COMENZI)} — nu se șterge, se poate dezactiva.</small>}
    </div>
  )
}
