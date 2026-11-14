import { useCallback, useState } from 'react'
import { useSearchParams } from 'react-router'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { useLoad } from '../../hooks/useLoad'
import { asApiError } from '../../services/api'
import { ItemDialog } from './ItemDialog'
import {
  dmy, lei, leiInput, num, packWord, parseLei, parseQty, stockApi,
  type Doc, type DocData, type DocsData, type Item, type LineIn, type ListData,
} from './stock'
import { Empty, F } from './parts'
import { useBindRetry, useStockCtx } from './StockScreen'

interface Row { id?: number; item_id: number; packs: string; sum: string; exp_on: string; lot: string }
const EMPTY: Row = { item_id: 0, packs: '', sum: '', exp_on: '', lot: '' }

/** Приход по накладной: список и редактор черновика (адрес `?v=intrari&doc=`). */
export function InvoiceView() {
  const { navigate, go, list } = useStockCtx()
  const [q] = useSearchParams()
  const open = q.get('doc')
  const load = useCallback((signal: AbortSignal) => stockApi.docs('factura', signal), [])
  const { state, retry } = useLoad<DocsData>(load, navigate)
  useBindRetry(retry)
  if (open) {
    if (!list) return <div className="fcard st-inv" aria-busy="true" />
    return open === 'nou' ? <Form key="nou" doc={null} list={list} onDone={() => go('intrari')} />
      : <Editor key={open} id={Number(open)} list={list} onDone={() => go('intrari')} />
  }
  if (state.status === 'failed') return <LoadFailed error={state.error} onRetry={retry} />
  if (state.status !== 'ready') return <div className="fcard rg-body" aria-busy="true" />
  const { docs, can } = state.data
  if (!docs.length) {
    return (
      <Empty ico="download" title="Încă nu e nicio factură">
        <p className="hint">Factura de la furnizor se introduce aici: furnizorul, numărul, data și rândurile în ambalaje — programul
          socotește singur gramele și bucățile. Până la „Înregistrează” rămâne ciornă și nu schimbă stocul.</p>
        <button type="button" className="rg-btn pri" onClick={() => go('intrari', { doc: 'nou' })}><Icon name="plus" /> Factură nouă</button>
      </Empty>
    )
  }
  return (
    <div className="fcard rg-body">
      <div className="rg-bar">
        <span className="rg-ttl"><b>Facturi de la furnizori</b><small>ciorna nu schimbă stocul; „Înregistrează” trece rândurile în mișcări</small></span>
        <button type="button" className="rg-btn pri" onClick={() => go('intrari', { doc: 'nou' })}><Icon name="plus" /> Factură nouă</button>
      </div>
      <div className="rg-scroll">
        <table className="rg-tbl st-tbl">
          <thead><tr><th>Data</th><th>Nr.</th><th>Furnizor</th><th className="num">Rânduri</th>{can.money && <th className="num">Suma</th>}<th>Stare</th><th /></tr></thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.id} className={d.status === 'ciorna' ? 'st-draft-r' : d.status === 'anulat' ? 'st-off-r' : ''}>
                <td className="num">{dmy(d.doc_date)}</td>
                <td><b>{d.nr || '—'}</b></td>
                <td>{d.supplier || '—'}</td>
                <td className="num">{d.lines}</td>
                {can.money && <td className="num">{d.total_bani ? lei(d.total_bani) : '—'}{d.no_sums && d.status === 'inchis' && <small className="st-warnt">fără sume</small>}</td>}
                <td><span className={`st-pill ${d.status === 'ciorna' ? 'warn' : d.status === 'anulat' ? 'mute' : 'ok'}`}>{d.status_label}</span><small>{d.actor}</small></td>
                <td className="st-act-c"><button type="button" className="rg-btn sm" onClick={() => go('intrari', { doc: String(d.id) })}>
                  {d.status === 'ciorna' ? <><Icon name="pen" /> Continuă</> : <><Icon name="eye" /> Deschide</>}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Editor({ id, list, onDone }: { id: number; list: ListData; onDone: () => void }) {
  const { navigate } = useStockCtx()
  /* редактор не отдаёт перечитывание корню: перечитанный документ стёр бы несохранённые строки черновика */
  const load = useCallback((signal: AbortSignal) => stockApi.doc(id, signal), [id])
  const { state, retry } = useLoad<DocData>(load, navigate)
  if (state.status === 'failed') return <LoadFailed error={state.error} onRetry={retry} />
  if (state.status !== 'ready') return <div className="fcard st-inv" aria-busy="true" />
  return <Form doc={state.data.doc} list={list} onDone={onDone} reload={retry} />
}

const packsOf = (qty: number | null, packQty: number) => (qty == null ? '' : num(Math.round((qty / packQty) * 1000), 3).split('.').join(''))

function Form({ doc, list, onDone, reload }: { doc: Doc | null; list: ListData; onDone: () => void; reload?: () => void }) {
  const { say, refresh } = useStockCtx()
  const money = list.can.money
  const ro = !!doc && doc.status !== 'ciorna'
  const suppliers = list.suppliers.filter((s) => s.active || s.id === doc?.supplier_id)
  const [docId, setDocId] = useState(doc?.id ?? 0)
  const [supplier, setSupplier] = useState(doc?.supplier_id ?? 0)
  const [newSup, setNewSup] = useState<{ name: string; idno: string } | null>(suppliers.length || doc ? null : { name: '', idno: '' })
  const [nr, setNr] = useState(doc?.nr ?? '')
  const [date, setDate] = useState(doc?.doc_date ?? list.today)
  const [rows, setRows] = useState<Row[]>(doc?.lines.length
    ? doc.lines.map((l) => ({ id: l.id, item_id: l.item_id, packs: packsOf(l.qty_milli, l.pack_qty_milli), sum: leiInput(l.cost_bani), exp_on: l.exp_on ?? '', lot: l.lot }))
    : [{ ...EMPTY }, { ...EMPTY }])
  const [bad, setBad] = useState<{ field: string; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [newItem, setNewItem] = useState<{ row: number; k: number } | null>(null)
  const [extra, setExtra] = useState<Item[]>([])
  const [sumsMode, setSumsMode] = useState(false)
  const [why, setWhy] = useState<string | null>(null)
  const live = [...list.items.filter((x) => x.active), ...extra]
  const itemOf = (iid: number) => live.find((x) => x.id === iid) ?? list.items.find((x) => x.id === iid)
  const lineOf = (r: Row) => doc?.lines.find((l) => l.id === r.id)
  const up = (i: number, p: Partial<Row>) => { setRows((ls) => ls.map((l, j) => (j === i ? { ...l, ...p } : l))); setBad(null) }
  const filled = rows.filter((l) => l.item_id)
  const qtyOf = (r: Row) => { const it = itemOf(r.item_id); const p = parseQty(r.packs); return it && p > 0 ? Math.round((p / 1000) * it.pack_qty_milli) : null }
  const total = filled.reduce((s, l) => s + (Number.isNaN(parseLei(l.sum)) ? 0 : parseLei(l.sum)), 0)
  const editSums = ro && sumsMode

  function body() {
    const lines: LineIn[] = filled.map((r) => ({
      ...(r.id ? { id: r.id } : {}), item_id: r.item_id, qty_milli: qtyOf(r), lot: r.lot.trim(), exp_on: r.exp_on || null,
      ...(money ? { cost_bani: r.sum.trim() && !Number.isNaN(parseLei(r.sum)) ? parseLei(r.sum) : null } : {}),
    }))
    const sup = newSup?.name.trim()
      ? { supplier_name: newSup.name.trim(), supplier_idno: newSup.idno.trim() } : { supplier_id: supplier || null }
    return { nr: nr.trim(), doc_date: date, ...sup, lines }
  }
  async function run(final: boolean) {
    if (final) {
      if (!supplier && !newSup?.name.trim()) { setBad({ field: 'supplier_id', text: 'Alegeți furnizorul.' }); return }
      if (!nr.trim()) { setBad({ field: 'nr', text: 'Scrieți numărul de pe factură.' }); return }
      if (!filled.length) { setBad({ field: 'lines', text: 'Adăugați cel puțin un rând cu material.' }); return }
      if (filled.some((r) => qtyOf(r) === null)) { setBad({ field: 'lines', text: 'Fiecare rând are nevoie de cantitate.' }); return }
      const noExp = filled.filter((r) => itemOf(r.item_id)?.track_expiry && !r.exp_on).length
      if (noExp && !(await ask({ text: `${noExp === 1 ? '1 rând nu are' : `${noExp} rânduri nu au`} termen de valabilitate. Înregistrați oricum?`, ok: 'Înregistrează' }))) return
    } else if (!filled.length && !nr.trim()) {
      setBad({ field: 'lines', text: 'Adăugați cel puțin un rând cu material.' }); return
    }
    setBusy(true)
    try {
      let target = docId
      if (target) await stockApi.saveDoc(target, body())
      else { const r = await stockApi.createDoc({ kind: 'factura', ...body() }); target = r.data.id; setDocId(target) }
      if (final) await stockApi.closeDoc(target)
      refresh()
      say(final ? `Factura ${nr.trim()} înregistrată: ${filled.length} rânduri au intrat în stoc.` : 'Ciorna facturii salvată. Stocul nu s-a schimbat.')
      onDone()
    } catch (e) {
      const err = asApiError(e)
      setBad({ field: err.field ?? '', text: err.text || 'Nu s-a salvat.' })
    } finally {
      setBusy(false)
    }
  }
  async function drop() {
    if (!docId) { onDone(); return }
    if (!(await ask({ text: `Ștergeți ciorna facturii „${nr || 'fără număr'}”? Stocul nu se schimbă.`, danger: true, ok: 'Șterge' }))) return
    try {
      await stockApi.dropDoc(docId)
      refresh()
      say('Ciorna ștearsă.')
      onDone()
    } catch (e) { setBad({ field: '', text: asApiError(e).text || 'Nu s-a șters.' }) }
  }
  async function saveSums() {
    const lines = rows.filter((r) => r.id && r.sum.trim()).map((r) => ({ id: r.id!, cost_bani: parseLei(r.sum) }))
    if (lines.some((l) => Number.isNaN(l.cost_bani))) { setBad({ field: 'lines', text: 'Suma — un număr, ex. 1680 sau 1680,50.' }); return }
    setBusy(true)
    try {
      await stockApi.sums(docId, lines)
      refresh()
      say('Sumele facturii completate.')
      setSumsMode(false)
      reload?.()
    } catch (e) { setBad({ field: '', text: asApiError(e).text || 'Nu s-a salvat.' }) } finally { setBusy(false) }
  }
  async function storno() {
    if (!why?.trim()) { setBad({ field: 'why', text: 'Scrieți de ce se anulează factura.' }); return }
    if (!(await ask({ text: `Anulați factura ${nr}? Rândurile ei ies din stoc cu rânduri inverse; factura rămâne în istorie ca anulată.`, danger: true, ok: 'Anulează factura' }))) return
    try {
      await stockApi.storno(docId, why.trim())
      refresh()
      say(`Factura ${nr} anulată.`)
      onDone()
    } catch (e) { const err = asApiError(e); setBad({ field: err.field ?? '', text: err.text || 'Nu se poate anula.' }) }
  }
  const b = (f: string) => (bad && bad.field === f ? bad.text : undefined)

  return (
    <div className="fcard st-inv">
      <div className="rg-bar">
        <span className="rg-ttl">
          <b>{doc ? `Factura ${doc.nr || 'fără număr'}` : 'Factură nouă'}</b>
          <small>{doc && ro ? `${doc.status_label} ${dmy(doc.closed_at)} · ${doc.actor}${doc.no_sums && doc.status === 'inchis' ? ' · fără sume' : ''}`
            : 'ciornă — stocul se schimbă doar la „Înregistrează”'}</small>
        </span>
        <button type="button" className="rg-btn" onClick={onDone}><Icon name="chev-l" /> Toate facturile</button>
      </div>
      <div className="st-inv-b">
        <div className="st-inv-h">
          <F label="Furnizorul" bad={b('supplier_id') ?? b('supplier_name')}>
            {ro ? <b>{doc!.supplier || '—'}</b> : newSup ? (
              <div className="st-newsup">
                <input className="dp-fld" value={newSup.name} maxLength={120} placeholder="Denumirea (ex. DentaMed SRL)" aria-label="Furnizor nou" onChange={(e) => { setNewSup({ ...newSup, name: e.target.value }); setBad(null) }} />
                <input className="dp-fld" value={newSup.idno} maxLength={13} inputMode="numeric" placeholder="IDNO (opțional)" aria-label="IDNO" onChange={(e) => setNewSup({ ...newSup, idno: e.target.value.replace(/\D/g, '') })} />
                {suppliers.length > 0 && <button type="button" className="dp-link" onClick={() => setNewSup(null)}>din listă</button>}
              </div>
            ) : (
              <span className="st-qrow">
                <select className="dp-sel" value={supplier} aria-label="Furnizorul" onChange={(e) => { setSupplier(Number(e.target.value)); setBad(null) }}>
                  <option value={0}>— alegeți —</option>
                  {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
                <button type="button" className="rg-btn sm" onClick={() => setNewSup({ name: '', idno: '' })}><Icon name="plus" /> Furnizor nou</button>
              </span>
            )}
          </F>
          <F label="Nr. facturii" bad={b('nr')}>
            {ro ? <b>{doc!.nr}</b> : <input className="dp-fld" value={nr} maxLength={40} placeholder="ex. DMD 004512" aria-label="Nr. facturii" onChange={(e) => { setNr(e.target.value); setBad(null) }} />}
          </F>
          <F label="Data facturii" bad={b('doc_date')}>{ro ? <b>{dmy(date)}</b> : <input className="dp-fld" type="date" value={date} max={list.today} aria-label="Data facturii" onChange={(e) => setDate(e.target.value)} />}</F>
        </div>
        {bad && !['supplier_id', 'supplier_name', 'nr', 'doc_date', 'why'].includes(bad.field) && <p className="st-err" role="alert">{bad.text}</p>}
        <div className="rg-scroll">
          <table className="rg-tbl st-lines">
            <thead>
              <tr><th>Material</th><th>Cantitate (ambalaje)</th><th>Intră în stoc</th>{money && <th>Suma rândului, MDL</th>}{money && <th>Preț / unitate</th>}<th>Valabil până la</th><th>Lot</th>{!ro && <th />}</tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const it = itemOf(r.item_id)
                const line = lineOf(r)
                const qty = qtyOf(r) ?? line?.qty_milli ?? null
                const unit = it?.unit ?? line?.unit ?? ''
                const sum = parseLei(r.sum)
                const unitPrice = qty && !Number.isNaN(sum) ? Math.round(sum / (qty / 1000)) : line?.unit_bani ?? 0
                const avg = line?.avg_bani ?? it?.avg_bani ?? 0
                const jump = unitPrice && avg && unitPrice > avg * 1.15 ? Math.round((unitPrice / avg - 1) * 100) : 0
                return (
                  <tr key={r.id ?? `n${i}`}>
                    <td className="st-l-item">
                      {ro ? <b>{line?.item ?? it?.name}</b> : (
                        <select className={`dp-sel${b('lines') && !r.item_id && i === 0 ? ' st-badf' : ''}`} value={r.item_id} aria-label={`Materialul, rândul ${i + 1}`}
                          onChange={(e) => { if (e.target.value === '-1') { setNewItem({ row: i, k: Date.now() }); return } up(i, { item_id: Number(e.target.value) }) }}>
                          <option value={0}>— alegeți —</option>
                          {live.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                          <option value={-1}>+ material nou…</option>
                        </select>
                      )}
                      {it && <small>{it.pack_name}</small>}
                    </td>
                    <td>{ro ? <b>{r.packs} × {it ? packWord(it) : ''}</b> : (
                      <span className="st-qrow"><input className={`dp-fld st-n${b('lines') && r.item_id && qtyOf(r) === null ? ' st-badf' : ''}`} inputMode="decimal" value={r.packs} placeholder="0"
                        aria-label={`Ambalaje, rândul ${i + 1}`} onChange={(e) => up(i, { packs: e.target.value })} />{it && <small className="st-mute">× {packWord(it)}</small>}</span>
                    )}</td>
                    <td className="num">{qty ? <b>+{num(qty)} {unit}</b> : <span className="st-mute">—</span>}</td>
                    {money && <td>{ro && !editSums ? (r.sum ? lei(parseLei(r.sum)) : <span className="st-warnt">fără sumă</span>) : (
                      <input className="dp-fld st-n" inputMode="decimal" value={r.sum} placeholder="0,00" aria-label={`Suma, rândul ${i + 1}`} onChange={(e) => up(i, { sum: e.target.value })} />
                    )}</td>}
                    {money && <td className="num">{unitPrice ? <>{lei(unitPrice)}{jump ? <small className="st-warnt">+{jump}% față de medie</small> : null}</> : <span className="st-mute">—</span>}</td>}
                    <td>{it?.track_expiry || r.exp_on ? (ro ? dmy(r.exp_on) : <input className="dp-fld st-date" type="date" value={r.exp_on} aria-label={`Termen, rândul ${i + 1}`} onChange={(e) => up(i, { exp_on: e.target.value })} />) : <span className="st-mute">—</span>}</td>
                    <td>{it?.costly || r.lot ? (ro ? (r.lot || '—') : <input className="dp-fld st-lot" value={r.lot} maxLength={60} placeholder="nr. lot" aria-label={`Lot, rândul ${i + 1}`} onChange={(e) => up(i, { lot: e.target.value })} />) : <span className="st-mute">—</span>}</td>
                    {!ro && <td className="st-act-c"><button type="button" className="rg-ib" aria-label={`Șterge rândul ${i + 1}`} onClick={() => setRows((ls) => (ls.length > 1 ? ls.filter((_, j) => j !== i) : [{ ...EMPTY }]))}><Icon name="trash" /></button></td>}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {!ro && <button type="button" className="rg-btn sm st-addl" onClick={() => setRows((ls) => [...ls, { ...EMPTY }])}><Icon name="plus" /> Încă un rând</button>}
        {!money && !ro && <p className="st-note"><Icon name="lock" /> Sumele și prețurile le vede și le completează directorul. Recepția introduce ce a venit, cât și până când e valabil.</p>}
        {doc && ro && <p className="hint"><Icon name="clipboard" /> O greșeală de cantitate se repară la inventariere{doc.can_storno && money ? ' sau cu „Anulează factura”' : ''}, nu cu ștergerea facturii.</p>}
        {why !== null && (
          <F label="De ce se anulează factura" bad={b('why')}>
            <input className="dp-fld" value={why} maxLength={300} autoFocus placeholder="ex. introdusă de două ori" aria-label="De ce se anulează factura" onChange={(e) => { setWhy(e.target.value); setBad(null) }} />
          </F>
        )}
      </div>
      <div className="rg-dlg-f st-foot">
        {money && filled.length > 0 && <span className="st-total">Total factură: <b>{lei(total)}</b></span>}
        {!ro && <button type="button" className="dp-btn ghost" onClick={() => { void drop() }}>{docId ? <><Icon name="trash" /> Șterge ciorna</> : 'Renunță'}</button>}
        {!ro && <button type="button" className="dp-btn" disabled={busy} onClick={() => { void run(false) }}><Icon name="save" /> Salvează ciorna</button>}
        {!ro && <button type="button" className="dp-btn pri" disabled={busy} onClick={() => { void run(true) }}><Icon name="check" /> Înregistrează</button>}
        {ro && doc?.status === 'inchis' && money && doc.no_sums && !editSums && <button type="button" className="dp-btn" onClick={() => setSumsMode(true)}><Icon name="money" /> Completează sumele</button>}
        {editSums && <button type="button" className="dp-btn pri" disabled={busy} onClick={() => { void saveSums() }}><Icon name="save" /> Salvează sumele</button>}
        {ro && doc?.can_storno && money && (why === null
          ? <button type="button" className="dp-btn ghost" onClick={() => setWhy('')}><Icon name="undo" /> Anulează factura</button>
          : <button type="button" className="dp-btn danger" onClick={() => { void storno() }}><Icon name="undo" /> Anulează factura</button>)}
      </div>
      {newItem && <ItemDialog key={newItem.k} id={0} onClose={() => setNewItem(null)}
        onSaved={(nid) => { const row = newItem.row; void stockApi.item(nid).then((r) => { setExtra((x) => [...x, r.data.item]); up(row, { item_id: nid }) }) }} />}
    </div>
  )
}
