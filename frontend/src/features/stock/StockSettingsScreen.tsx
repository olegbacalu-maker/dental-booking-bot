import { useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type ScreenData } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { stockApi, type ConsumeMode, type ListData, type Supplier } from './stock'
import { F } from './parts'

type Draft = { id?: number; name: string; idno: string; phone: string; email: string; note: string; active: boolean }
const NEW: Draft = { name: '', idno: '', phone: '', email: '', note: '', active: true }

export const loadStockSettings: ScreenData = (signal) => stockApi.list(signal)

/** Setări › Stoc: когда «expiră în curând» и когда гаснет «comandat»; справочник поставщиков. */
export function StockSettingsScreen({ navigate = defaultNavigate }: { navigate?: (url: string) => void }) {
  const { state, retry } = useRouteLoad<ListData>(navigate, { keep: true })
  const [toast, setToast] = useState<ToastState | null>(null)
  const [days, setDays] = useState<{ exp: string; ord: string; mode: ConsumeMode } | null>(null)
  const [edit, setEdit] = useState<Draft | null>(null)
  const [bad, setBad] = useState<{ field: string; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  if (state.status === 'leaving') return null
  if (state.status === 'failed') return <section className="dp-react-root"><LoadFailed error={state.error} onRetry={retry} /></section>
  if (state.status !== 'ready') return <section className="dp-react-root" aria-busy="true"><div className="fcard" /></section>
  const d = state.data
  const cur = days ?? { exp: String(d.prefs.exp_days), ord: String(d.prefs.order_days), mode: d.prefs.tc_mode ?? 'confirmare' }
  const say = (text: string, tone: ToastState['tone'] = 'ok') => setToast({ text, tone })

  async function savePrefs() {
    setBusy(true)
    try {
      await stockApi.prefs({ exp_days: Number(cur.exp), order_days: Number(cur.ord), tc_mode: cur.mode })
      setDays(null)
      retry()
      say('Setările stocului salvate.')
    } catch (e) { const er = asApiError(e); setBad({ field: er.field ?? 'prefs', text: er.text || 'Nu s-a salvat.' }) } finally { setBusy(false) }
  }
  async function saveSup() {
    if (!edit) return
    if (!edit.name.trim()) { setBad({ field: 'name', text: 'Scrieți denumirea.' }); return }
    setBusy(true)
    try {
      await stockApi.saveSupplier({ ...(edit.id ? { id: edit.id } : {}), name: edit.name.trim(), idno: edit.idno.trim(), phone: edit.phone.trim(),
        email: edit.email.trim(), note: edit.note.trim(), active: edit.active })
      setEdit(null)
      retry()
      say('Furnizorul salvat.')
    } catch (e) { const er = asApiError(e); setBad({ field: er.field ?? '', text: er.text || 'Nu s-a salvat.' }) } finally { setBusy(false) }
  }
  async function dropSup(s: Supplier) {
    if (!(await ask({ text: `Ștergeți furnizorul „${s.name}”?`, danger: true, ok: 'Șterge' }))) return
    try { await stockApi.dropSupplier(s.id); retry(); say('Furnizorul șters.') } catch (e) { say(asApiError(e).text || 'Nu s-a șters.', 'err') }
  }
  const b = (f: string) => (bad && bad.field === f ? bad.text : undefined)
  const up = (p: Partial<Draft>) => { setEdit((x) => (x ? { ...x, ...p } : x)); setBad(null) }

  return (
    <section className="dp-react-root rg st">
      <div className="fcard st-inv">
        <div className="rg-bar"><span className="rg-ttl"><b>Semnale și scădere</b><small>ce apare în „Expiră curând”, când se stinge nota „comandat” și cum se scad materialele la finalizare</small></span>
          <AppLink className="rg-btn" href="/admin/stoc"><Icon name="box" /> La stoc</AppLink></div>
        <div className="st-inv-b">
          <div className="st-two">
            <F label="„Expiră în curând” — cu câte zile înainte" bad={b('exp_days')} hint="de la 1 la 365">
              <input className="dp-fld st-n" inputMode="numeric" value={cur.exp} disabled={!d.can.settings} aria-label="Zile expiră"
                onChange={(e) => { setDays({ ...cur, exp: e.target.value.replace(/\D/g, '').slice(0, 3) }); setBad(null) }} />
            </F>
            <F label="„Comandat” se stinge după câte zile fără factură" bad={b('order_days')} hint="de la 1 la 60; atunci rândul spune „n-a venit”">
              <input className="dp-fld st-n" inputMode="numeric" value={cur.ord} disabled={!d.can.settings} aria-label="Zile comandat"
                onChange={(e) => { setDays({ ...cur, ord: e.target.value.replace(/\D/g, '').slice(0, 2) }); setBad(null) }} />
            </F>
          </div>
          <F label="Scădere la finalizare" bad={b('tc_mode')}
            hint={cur.mode === 'confirmare' ? 'la „Finalizată” în plan se deschide lista materialelor serviciului — se corectează și se confirmă'
              : cur.mode === 'automat' ? 'materialele serviciului se scad singure la „Finalizată”; corecția — la inventariere'
                : 'materialele se scad doar de mână, din „Stoc”'}>
            <span className="dp-seg st-seg" role="group" aria-label="Scădere la finalizare">
              {([['fara', 'fără'], ['confirmare', 'cu confirmare'], ['automat', 'automat']] as [ConsumeMode, string][]).map(([k, label]) => (
                <button key={k} type="button" className={cur.mode === k ? 'on' : ''} aria-pressed={cur.mode === k} disabled={!d.can.settings}
                  onClick={() => { setDays({ ...cur, mode: k }); setBad(null) }}>{label}</button>
              ))}
            </span>
          </F>
          {b('prefs') && <p className="st-err" role="alert">{b('prefs')}</p>}
          {!d.can.settings && <p className="st-note"><Icon name="lock" /> Aceste setări le schimbă directorul.</p>}
        </div>
        {d.can.settings && days && (
          <div className="rg-dlg-f st-foot"><button type="button" className="dp-btn pri" disabled={busy} onClick={() => { void savePrefs() }}><Icon name="save" /> Salvează</button></div>
        )}
      </div>

      <div className="fcard rg-body">
        <div className="rg-bar"><span className="rg-ttl"><b>Furnizori</b><small>numele, IDNO și telefonul — pe facturi și în lista „De cumpărat”</small></span>
          <button type="button" className="rg-btn pri" onClick={() => { setEdit({ ...NEW }); setBad(null) }}><Icon name="plus" /> Furnizor nou</button></div>
        {edit && (
          <div className="st-inv-b st-supedit">
            <div className="st-two">
              <F label="Denumirea" bad={b('name')}><input className="dp-fld" value={edit.name} maxLength={120} autoFocus aria-label="Denumirea" onChange={(e) => up({ name: e.target.value })} /></F>
              <F label="IDNO" bad={b('idno')} hint="13 cifre sau gol"><input className="dp-fld" value={edit.idno} maxLength={13} inputMode="numeric" aria-label="IDNO" onChange={(e) => up({ idno: e.target.value.replace(/\D/g, '') })} /></F>
              <F label="Telefon"><input className="dp-fld" value={edit.phone} maxLength={30} aria-label="Telefon" onChange={(e) => up({ phone: e.target.value })} /></F>
              <F label="E-mail" bad={b('email')}><input className="dp-fld" value={edit.email} maxLength={120} aria-label="E-mail" onChange={(e) => up({ email: e.target.value })} /></F>
            </div>
            <F label="Notă"><input className="dp-fld" value={edit.note} maxLength={300} placeholder="ex. livrare marți și vineri" aria-label="Notă" onChange={(e) => up({ note: e.target.value })} /></F>
            {edit.id && <label className="st-chk"><input type="checkbox" checked={!edit.active} onChange={(e) => up({ active: !e.target.checked })} /> nu mai lucrăm cu el (rămâne în istorie)</label>}
            {bad && !['name', 'idno', 'email'].includes(bad.field) && <p className="st-err" role="alert">{bad.text}</p>}
            <span className="st-qrow">
              <button type="button" className="dp-btn" onClick={() => setEdit(null)}>Renunță</button>
              <button type="button" className="dp-btn pri" disabled={busy} onClick={() => { void saveSup() }}><Icon name="save" /> Salvează</button>
            </span>
          </div>
        )}
        {d.suppliers.length === 0 ? <p className="hint rg-none">Lista e goală. Furnizorii se adaugă și direct din factură.</p> : (
          <div className="rg-scroll">
            <table className="rg-tbl st-tbl">
              <thead><tr><th>Furnizor</th><th>IDNO</th><th>Telefon</th><th className="num">Materiale</th><th className="num">Facturi</th><th /></tr></thead>
              <tbody>
                {d.suppliers.map((s) => (
                  <tr key={s.id} className={s.active ? '' : 'st-off-r'}>
                    <td><b>{s.name}</b>{(s.note || !s.active) && <small>{s.active ? s.note : 'nu mai lucrăm cu el'}</small>}</td>
                    <td className="num">{s.idno || '—'}</td>
                    <td className="num">{s.phone || '—'}</td>
                    <td className="num">{s.items}</td>
                    <td className="num">{s.docs}</td>
                    <td className="st-act-c">
                      <button type="button" className="rg-ib" aria-label={`Editează ${s.name}`} onClick={() => { setEdit({ id: s.id, name: s.name, idno: s.idno, phone: s.phone, email: s.email, note: s.note, active: s.active }); setBad(null) }}><Icon name="pen" /></button>
                      {!s.items && !s.docs && <button type="button" className="rg-ib" aria-label={`Șterge ${s.name}`} onClick={() => { void dropSup(s) }}><Icon name="trash" /></button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {toast && <Toast {...toast} onClose={() => setToast(null)} />}
    </section>
  )
}
