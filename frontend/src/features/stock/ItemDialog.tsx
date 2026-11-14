import { useEffect, useRef, useState } from 'react'
import { ask } from '../../components/confirm'
import { hideDialog, showDialog } from '../../components/dialog'
import { Icon } from '../../components/Icon'
import { asApiError } from '../../services/api'
import { dmy, lei, num, parseQty, qtyText, stockApi, UNITS, type ItemCard, type Supplier, type Unit } from './stock'
import { F, KindPill, Signed } from './parts'
import { useStockCtx } from './StockScreen'

interface Draft {
  name: string; cat: string; newCat: string; unit: Unit; pack: string; packQty: string; min: string
  costly: boolean; expiry: boolean; bulk: boolean; supplier: number; note: string; raft: string; active: boolean; start: string
}

const EMPTY: Draft = { name: '', cat: '', newCat: '', unit: 'buc', pack: '', packQty: '1', min: '', costly: false, expiry: false, bulk: false,
  supplier: 0, note: '', raft: '', active: true, start: '' }

/** Число для поля ввода: «4», «3,8», без разделителя тысяч. */
const plain = (milli: number) => num(milli, 3).split('.').join('')

/** Fișa materialului: две единицы, порог, признаки; у существующего — партии, движения, цены (директор). */
export function ItemDialog({ id, onClose, onSaved }: { id: number; onClose: () => void; onSaved?: (id: number) => void }) {
  const { say, refresh, list } = useStockCtx()
  const ref = useRef<HTMLDialogElement>(null)
  const [card, setCard] = useState<ItemCard | null>(null)
  const [d, setD] = useState<Draft>(EMPTY)
  const [bad, setBad] = useState<{ field: string; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { showDialog(ref.current); const r = ref.current; return () => hideDialog(r) }, [])
  useEffect(() => {
    if (!id) return
    const ctl = new AbortController()
    stockApi.item(id, ctl.signal).then((r) => {
      const it = r.data.item
      setCard(r.data)
      setD({ name: it.name, cat: it.cat, newCat: '', unit: it.unit, pack: it.pack_name, packQty: plain(it.pack_qty_milli),
        min: it.min_milli === null ? '' : plain(it.min_milli), costly: it.costly, expiry: it.track_expiry, bulk: it.bulk,
        supplier: it.supplier_id ?? 0, note: it.note, raft: it.data.raft ?? '', active: it.active, start: '' })
    }).catch((e: unknown) => { if (!ctl.signal.aborted) setBad({ field: '', text: asApiError(e).text || 'Fișa nu s-a deschis.' }) })
    return () => ctl.abort()
  }, [id])
  const up = (p: Partial<Draft>) => { setD((x) => ({ ...x, ...p })); setBad(null) }
  const suppliers: Supplier[] = (list?.suppliers ?? []).filter((x) => x.active || x.id === d.supplier)
  const cats = list?.cats ?? []
  const pq = parseQty(d.packQty)
  const min = parseQty(d.min)
  const it = card?.item
  const money = card?.can.money ?? list?.can.money ?? false
  /* единица материала с движениями не меняется: все количества журнала записаны в старой */
  const locked = (it?.moves ?? 0) > 0

  async function drop() {
    if (!it) return
    if (!(await ask({ text: `Ștergeți materialul „${it.name}”? Nu are nicio mișcare, deci nu se pierde nimic din istorie.`, danger: true, ok: 'Șterge' }))) return
    try {
      await stockApi.dropItem(it.id)
      refresh()
      say(`„${it.name}” șters din catalog.`)
      onClose()
    } catch (e) {
      setBad({ field: '', text: asApiError(e).text || 'Nu s-a șters.' })
    }
  }

  async function save() {
    const cat = d.cat === '+' ? d.newCat.trim() : d.cat
    const start = parseQty(d.start)
    if (!d.name.trim()) { setBad({ field: 'name', text: 'Scrieți denumirea.' }); return }
    if (!cat) { setBad({ field: 'cat', text: 'Alegeți categoria.' }); return }
    if (Number.isNaN(pq) || pq <= 0) { setBad({ field: 'pack_qty_milli', text: 'Un număr mai mare ca zero.' }); return }
    if (d.min.trim() && (Number.isNaN(min) || min < 0)) { setBad({ field: 'min_milli', text: 'Un număr sau gol.' }); return }
    if (!id && d.start.trim() && Number.isNaN(start)) { setBad({ field: 'shelf_milli', text: 'Un număr sau gol.' }); return }
    setBusy(true)
    try {
      const r = await stockApi.saveItem({
        ...(id ? { id } : {}), name: d.name.trim(), cat, ...(locked ? {} : { unit: d.unit }), pack_name: d.pack.trim(), pack_qty_milli: pq,
        min_milli: d.min.trim() ? min : null, costly: d.costly, track_expiry: d.expiry, bulk: d.bulk,
        supplier_id: d.supplier || null, note: d.note.trim(), active: d.active, data: { ...(it?.data ?? {}), raft: d.raft.trim() },
        ...(!id && start > 0 ? { shelf_milli: start } : {}),
      })
      refresh()
      say(id ? `Fișa „${d.name.trim()}” salvată.` : `„${d.name.trim()}” adăugat în catalog.`)
      onSaved?.(r.data.id)
      onClose()
    } catch (e) {
      const err = asApiError(e)
      setBad({ field: err.field ?? '', text: err.text || 'Nu s-a salvat.' })
    } finally {
      setBusy(false)
    }
  }
  const b = (f: string) => (bad && bad.field === f ? bad.text : undefined)

  return (
    <dialog ref={ref} className="rg-dlg wide st-dlg" onClose={onClose} aria-label="Fișa materialului">
      <div className="dlg-head">
        <span><Icon name="box" /> {id ? it?.name ?? '…' : 'Material nou'}</span>
        <button type="button" className="rg-x" onClick={onClose} aria-label="Închide"><Icon name="close" /></button>
      </div>
      <div className="rg-dlg-b">
        {it && (
          <div className="st-now">
            <span><small>Rest acum</small><b className={it.neg ? 'st-neg' : it.low ? 'st-lowt' : ''}>{qtyText(it.qty_milli, it.unit)}</b></span>
            {it.min_milli !== null && <span><small>Prag</small><b>{qtyText(it.min_milli, it.unit)}</b></span>}
            {money && <span><small>Preț mediu</small><b>{it.avg_bani ? `${lei(it.avg_bani)} / ${it.unit}` : '—'}</b></span>}
            {it.lots.length > 0 && <span className="st-lots"><small>Loturi pe raft</small>{it.lots.map((x, i) => (
              <em key={i}>{x.lot || 'fără lot'} · {x.exp_on ? `până la ${dmy(x.exp_on)}` : 'fără termen'} · {qtyText(x.qty_milli, it.unit)}</em>
            ))}</span>}
          </div>
        )}
        {bad && !['name', 'cat', 'unit', 'pack_qty_milli', 'min_milli', 'shelf_milli'].includes(bad.field) && <p className="st-err" role="alert">{bad.text}</p>}
        <F label="Denumirea" bad={b('name')}>
          <input className="dp-fld" value={d.name} maxLength={90} onChange={(e) => up({ name: e.target.value })} placeholder="ex. Filtek Z550 A2" autoFocus={!id} />
        </F>
        <div className="st-two">
          <F label="Categoria" bad={b('cat')}>
            <select className="dp-sel" value={d.cat} onChange={(e) => up({ cat: e.target.value, ...(e.target.value === 'Consumabile diverse' ? { bulk: true, costly: false } : {}) })}>
              <option value="">— alegeți —</option>
              {cats.map((c) => <option key={c}>{c}</option>)}
              <option value="+">altă categorie…</option>
            </select>
            {d.cat === '+' && <input className="dp-fld" value={d.newCat} maxLength={40} placeholder="Numele categoriei" aria-label="Categorie nouă" onChange={(e) => up({ newCat: e.target.value })} />}
          </F>
          <F label="Furnizorul obișnuit">
            <select className="dp-sel" value={d.supplier} onChange={(e) => up({ supplier: Number(e.target.value) })}>
              <option value={0}>—</option>
              {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </F>
        </div>
        <F label="Se scade în" bad={b('unit')} hint={locked ? 'nu se schimbă: mișcările sunt deja scrise în această unitate' : 'unitatea în care se consumă: carpula, gramul de compozit, mililitrul'}>
          <div className="rg-chips" role="group" aria-label="Unitatea">
            {UNITS.map((u) => (
              <button key={u} type="button" className={`rg-chip sm${d.unit === u ? ' on' : ''}`} aria-pressed={d.unit === u} disabled={locked && d.unit !== u} onClick={() => up({ unit: u })}>{u}</button>
            ))}
          </div>
        </F>
        <div className="st-two">
          <F label="Se cumpără în (ambalaj)" hint="cum scrie pe factură">
            <input className="dp-fld" value={d.pack} maxLength={40} placeholder="ex. seringă 4 g, cutie 50 carpule" onChange={(e) => up({ pack: e.target.value })} />
          </F>
          <F label={`Câte ${d.unit} într-un ambalaj`} bad={b('pack_qty_milli')} hint="1 — se cumpără și se scade la fel">
            <input className="dp-fld st-n" inputMode="decimal" value={d.packQty} onChange={(e) => up({ packQty: e.target.value })} aria-label={`Câte ${d.unit} într-un ambalaj`} />
          </F>
        </div>
        <div className="st-two">
          <F label={`Prag „de comandat”, ${d.unit}`} bad={b('min_milli')}
            hint={!Number.isNaN(min) && pq > 1000 ? `~${num((min / pq) * 1000, 1)} ambalaje; gol — fără prag` : 'sub prag apare în „De cumpărat”; gol — fără prag'}>
            <input className="dp-fld st-n" inputMode="decimal" value={d.min} onChange={(e) => up({ min: e.target.value })} aria-label="Prag" />
          </F>
          {!id && (
            <F label={`Acum pe raft, ${d.unit}`} bad={b('shelf_milli')} hint="restul de pornire; se scrie ca inventariere">
              <input className="dp-fld st-n" inputMode="decimal" value={d.start} placeholder="0" onChange={(e) => up({ start: e.target.value })} aria-label="Acum pe raft" />
            </F>
          )}
        </div>
        <div className="st-checks">
          <label><input type="checkbox" checked={d.expiry} onChange={(e) => up({ expiry: e.target.checked })} /> <span><b>Are termen de valabilitate</b><small>la intrare se cere data; apare în „expiră în curând”</small></span></label>
          <label><input type="checkbox" checked={d.costly} onChange={(e) => up({ costly: e.target.checked, ...(e.target.checked ? { bulk: false } : {}) })} /> <span><b>Scump, pe bucată</b><small>implant, abutment, membrană: se scade pe pacient, cu numărul lotului</small></span></label>
          <label><input type="checkbox" checked={d.bulk} onChange={(e) => up({ bulk: e.target.checked, ...(e.target.checked ? { costly: false } : {}) })} /> <span><b>Consumabile diverse</b><small>ieftin, nu se numără pe bucată: se scade un pachet la deschidere</small></span></label>
          {id > 0 && <label><input type="checkbox" checked={!d.active} onChange={(e) => up({ active: !e.target.checked })} /> <span><b>Scos din uz (arhivă)</b><small>nu se șterge: istoria rămâne în mișcări</small></span></label>}
        </div>
        <div className="st-two">
          <F label="Unde stă"><input className="dp-fld" value={d.raft} maxLength={60} onChange={(e) => up({ raft: e.target.value })} placeholder="ex. dulap 1, sertar 2" aria-label="Unde stă" /></F>
          <F label="Notă"><input className="dp-fld" value={d.note} maxLength={500} onChange={(e) => up({ note: e.target.value })} placeholder="cod la furnizor" aria-label="Notă" /></F>
        </div>
        {card && card.moves.length > 0 && (
          <div className="rg-f">
            <span className="rg-fl">Ultimele mișcări</span>
            <ul className="st-hist">
              {card.moves.map((m) => (
                <li key={m.id}><span>{dmy(m.at)}</span><KindPill m={m} /><Signed q={m.qty_milli} unit={m.unit} />
                  <small>{[m.patient, m.lot && `lot ${m.lot}`, m.note, m.actor].filter(Boolean).join(' · ')}</small></li>
              ))}
            </ul>
          </div>
        )}
        {card?.prices && card.prices.length > 1 && it && (
          <div className="rg-f">
            <span className="rg-fl">Prețul la ultimele intrări</span>
            <ul className="st-hist">
              {card.prices.map((p, i) => <li key={i}><span>{dmy(p.on)}</span><b>{lei(p.unit_bani)} / {it.unit}</b><small>{[p.nr, p.supplier].filter(Boolean).join(' · ')}</small></li>)}
            </ul>
          </div>
        )}
      </div>
      <div className="rg-dlg-f">
        {it && it.moves === 0 && <button type="button" className="dp-btn ghost" onClick={() => { void drop() }}><Icon name="trash" /> Șterge</button>}
        <button type="button" className="dp-btn" onClick={onClose}>Renunță</button>
        <button type="button" className="dp-btn pri" disabled={busy || (id > 0 && !card)} onClick={() => { void save() }}><Icon name="save" /> {id ? 'Salvează' : 'Adaugă în catalog'}</button>
      </div>
    </dialog>
  )
}
