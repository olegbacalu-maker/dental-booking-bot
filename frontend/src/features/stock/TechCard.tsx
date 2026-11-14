import { useEffect, useRef, useState } from 'react'
import { ask } from '../../components/confirm'
import { hideDialog, showDialog } from '../../components/dialog'
import { Icon } from '../../components/Icon'
import { asApiError } from '../../services/api'
import { num, parseQty, stockApi, type TechCards, type TechLine } from './stock'

interface Row { item_id: number; qty: string; optional: boolean }

const plain = (milli: number) => num(milli, 3).split('.').join('')

/** Техкарта услуги: материалы и количество на одну услугу — из неё строится окно при «finalizat» (ступень 2). */
export function TechCardDialog({ svc, name, tc, onClose, onSaved }: {
  svc: string; name: string; tc: TechCards; onClose: () => void; onSaved: (lines: TechLine[], text: string) => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const start = tc.cards[svc] ?? []
  const [rows, setRows] = useState<Row[]>(() => (start.length ? start : []).map((l) => ({ item_id: l.item_id, qty: plain(l.qty_milli), optional: l.optional })))
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { showDialog(ref.current); const r = ref.current; return () => hideDialog(r) }, [])
  const itemOf = (id: number) => tc.items.find((x) => x.id === id)
  const nameOf = (id: number) => itemOf(id)?.name ?? start.find((l) => l.item_id === id)?.item ?? '—'
  const up = (i: number, p: Partial<Row>) => { setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...p } : r))); setErr('') }
  const move = (i: number, d: -1 | 1) => setRows((rs) => {
    const j = i + d
    if (j < 0 || j >= rs.length) return rs
    const next = [...rs]
    ;[next[i], next[j]] = [next[j]!, next[i]!]
    return next
  })
  const live = tc.items.filter((x) => x.active)
  const canEdit = tc.can.settings

  async function save() {
    const filled = rows.filter((r) => r.item_id)
    if (filled.some((r) => !(parseQty(r.qty) > 0))) { setErr('Fiecare material are nevoie de cantitate, ex. 0,3 sau 1.'); return }
    if (new Set(filled.map((r) => r.item_id)).size !== filled.length) { setErr('Un material apare de două ori — lăsați un singur rând.'); return }
    setBusy(true)
    try {
      const lines = filled.map((r) => ({ item_id: r.item_id, qty_milli: parseQty(r.qty), optional: r.optional }))
      const res = await stockApi.saveTechcard(svc, lines)
      onSaved(lines.map((l, i) => ({ ...l, item: nameOf(l.item_id), unit: itemOf(l.item_id)?.unit ?? '', sort: i, active: itemOf(l.item_id)?.active ?? true })),
        res.text || `Materialele pentru „${name}” salvate.`)
      onClose()
    } catch (e) { setErr(asApiError(e).text || 'Nu s-a salvat.') } finally { setBusy(false) }
  }

  return (
    <div className="rg st st-host">
    <dialog ref={ref} className="rg-dlg wide st-dlg" onClose={onClose} aria-label={`Materiale: ${name}`}>
      <div className="dlg-head">
        <span><Icon name="box" /> Materiale pentru „{name}”</span>
        <button type="button" className="rg-x" onClick={onClose} aria-label="Închide"><Icon name="close" /></button>
      </div>
      <div className="rg-dlg-b">
        <p className="hint">Ce se consumă de obicei la o singură „{name}”. La „Finalizată” în planul pacientului lista apare gata
          completată — medicul sau asistenta corectează cantitatea și confirmă. „Opțional” — vine nebifat.</p>
        {rows.length === 0 && <p className="hint st-tc-none">Încă niciun material — serviciul se finalizează fără scădere din stoc.</p>}
        {rows.length > 0 && (
          <table className="st-tc">
            <thead><tr><th>Material</th><th>Cantitate</th><th>Opțional</th><th /></tr></thead>
            <tbody>
              {rows.map((r, i) => {
                const it = itemOf(r.item_id)
                return (
                  <tr key={i}>
                    <td>
                      {canEdit ? (
                        <select className="dp-sel" value={r.item_id} aria-label={`Materialul ${i + 1}`} onChange={(e) => up(i, { item_id: Number(e.target.value) })}>
                          <option value={0}>— alegeți —</option>
                          {it && !it.active && <option value={it.id}>{it.name} (în arhivă)</option>}
                          {live.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                        </select>
                      ) : <b>{nameOf(r.item_id)}</b>}
                      {it && !it.active && <small className="st-warnt">în arhivă — alegeți altul sau înlocuiți-l în toate serviciile</small>}
                    </td>
                    <td><span className="st-qrow"><input className="dp-fld st-n" inputMode="decimal" value={r.qty} disabled={!canEdit} aria-label={`Cantitatea ${i + 1}`}
                      onChange={(e) => up(i, { qty: e.target.value })} /><small className="st-mute">{it?.unit ?? ''}</small></span></td>
                    <td className="st-tc-c"><input type="checkbox" checked={r.optional} disabled={!canEdit} aria-label={`Opțional ${i + 1}`} onChange={(e) => up(i, { optional: e.target.checked })} /></td>
                    <td className="st-act-c">{canEdit && (
                      <span className="st-qrow">
                        <button type="button" className="rg-ib" aria-label={`Mai sus ${i + 1}`} disabled={i === 0} onClick={() => move(i, -1)}><Icon name="caret-u" /></button>
                        <button type="button" className="rg-ib" aria-label={`Mai jos ${i + 1}`} disabled={i === rows.length - 1} onClick={() => move(i, 1)}><Icon name="caret-d" /></button>
                        <button type="button" className="rg-ib" aria-label={`Șterge ${i + 1}`} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}><Icon name="trash" /></button>
                      </span>
                    )}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        {canEdit && <button type="button" className="rg-btn sm st-addl" onClick={() => setRows((rs) => [...rs, { item_id: 0, qty: '', optional: false }])}><Icon name="plus" /> Adaugă material</button>}
        {!canEdit && <p className="st-note"><Icon name="lock" /> Materialele serviciilor le schimbă directorul.</p>}
        {err && <p className="st-err" role="alert">{err}</p>}
      </div>
      <div className="rg-dlg-f">
        <button type="button" className="dp-btn" onClick={onClose}>{canEdit ? 'Renunță' : 'Închide'}</button>
        {canEdit && <button type="button" className="dp-btn pri" disabled={busy} onClick={() => { void save() }}><Icon name="save" /> Salvează</button>}
      </div>
    </dialog>
    </div>
  )
}

/** «Înlocuiește materialul în toate serviciile»: другой бренд или размер — одной командой во всех техкартах. */
export function ReplaceDialog({ tc, onClose, onDone }: { tc: TechCards; onClose: () => void; onDone: (text: string) => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const [from, setFrom] = useState(0)
  const [to, setTo] = useState(0)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { showDialog(ref.current); const r = ref.current; return () => hideDialog(r) }, [])
  const used = new Map<number, { name: string; unit: string; n: number }>()
  for (const lines of Object.values(tc.cards)) for (const l of lines) {
    const u = used.get(l.item_id) ?? { name: l.item, unit: l.unit, n: 0 }
    u.n += 1
    used.set(l.item_id, u)
  }
  const src = used.get(from)
  const targets = tc.items.filter((x) => x.active && x.id !== from && (!src || x.unit === src.unit))

  async function run() {
    if (!from || !to) { setErr('Alegeți ambele materiale.'); return }
    const dst = tc.items.find((x) => x.id === to)!
    if (!(await ask({ text: `Înlocuiți „${src!.name}” cu „${dst.name}” în ${src!.n === 1 ? '1 serviciu' : `${src!.n} servicii`}? Cantitățile rămân aceleași.`, ok: 'Înlocuiește' }))) return
    setBusy(true)
    try {
      const r = await stockApi.replaceInCards(from, to)
      onDone(r.text || `Înlocuit în ${r.data.services} servicii.`)
      onClose()
    } catch (e) { setErr(asApiError(e).text || 'Nu s-a înlocuit.') } finally { setBusy(false) }
  }

  return (
    <div className="rg st st-host">
    <dialog ref={ref} className="rg-dlg st-dlg" onClose={onClose} aria-label="Înlocuiește materialul în toate serviciile">
      <div className="dlg-head">
        <span><Icon name="refresh" /> Înlocuiește materialul în toate serviciile</span>
        <button type="button" className="rg-x" onClick={onClose} aria-label="Închide"><Icon name="close" /></button>
      </div>
      <div className="rg-dlg-b">
        <p className="hint">Când clinica trece la alt brand sau alt ambalaj — de ex. alt anestezic — se schimbă o dată în toate serviciile.</p>
        <div className="rg-f"><span className="rg-fl">Materialul de acum</span>
          <select className="dp-sel" value={from} aria-label="Materialul de acum" onChange={(e) => { setFrom(Number(e.target.value)); setTo(0); setErr('') }}>
            <option value={0}>— alegeți —</option>
            {[...used.entries()].map(([id, u]) => <option key={id} value={id}>{u.name} — în {u.n === 1 ? '1 serviciu' : `${u.n} servicii`}</option>)}
          </select>
        </div>
        <div className="rg-f"><span className="rg-fl">Materialul nou</span>
          <select className="dp-sel" value={to} disabled={!from} aria-label="Materialul nou" onChange={(e) => { setTo(Number(e.target.value)); setErr('') }}>
            <option value={0}>— alegeți —</option>
            {targets.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
          {src && <small className="hint">doar materiale în aceeași unitate ({src.unit}) — cantitățile rămân aceleași</small>}
        </div>
        {err && <p className="st-err" role="alert">{err}</p>}
      </div>
      <div className="rg-dlg-f">
        <button type="button" className="dp-btn" onClick={onClose}>Renunță</button>
        <button type="button" className="dp-btn pri" disabled={busy || !from || !to} onClick={() => { void run() }}><Icon name="refresh" /> Înlocuiește</button>
      </div>
    </dialog>
    </div>
  )
}
