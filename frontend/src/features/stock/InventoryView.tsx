import { useCallback, useState } from 'react'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { useLoad } from '../../hooks/useLoad'
import { asApiError } from '../../services/api'
import { dmy, lei, num, parseQty, qtyText, stockApi, type Doc, type DocData, type DocsData, type ListData } from './stock'
import { Empty } from './parts'
import { useBindRetry, useStockCtx } from './StockScreen'

/** Инвентаризация: «în program» против «pe raft», черновик на завтра, «Aplică» — разница строками журнала. */
export function InventoryView() {
  const { navigate, list, refresh } = useStockCtx()
  const [open, setOpen] = useState<number | 'nou' | null>(null)
  const load = useCallback((signal: AbortSignal) => stockApi.docs('inventar', signal), [])
  const { state, retry } = useLoad<DocsData>(load, navigate)
  useBindRetry(retry)
  if (!list) return <div className="fcard rg-body" aria-busy="true" />
  if (open === 'nou') return <Start list={list} onCancel={() => setOpen(null)} onMade={(id) => { refresh(); setOpen(id) }} />
  if (open !== null) return <Sheet key={open} id={open} list={list} onDone={() => { setOpen(null); retry() }} />
  if (state.status === 'failed') return <LoadFailed error={state.error} onRetry={retry} />
  if (state.status !== 'ready') return <div className="fcard rg-body" aria-busy="true" />
  if (!list.items.length) {
    return (
      <Empty ico="check" title="Inventarierea are nevoie de catalog">
        <p className="hint">Mai întâi lista materialelor (din Excel sau câte unul). Prima inventariere este de fapt restul de pornire.</p>
      </Empty>
    )
  }
  const docs = state.data.docs
  return (
    <div className="fcard rg-body">
      <div className="rg-bar">
        <span className="rg-ttl"><b>Inventarieri</b><small>o dată pe lună sau pe trimestru; se poate și doar pe o categorie</small></span>
        <button type="button" className="rg-btn pri" onClick={() => setOpen('nou')}><Icon name="plus" /> Inventariere nouă</button>
      </div>
      {docs.length === 0 ? <p className="hint rg-none">Încă nu s-a făcut nicio inventariere.</p> : (
        <div className="rg-scroll">
          <table className="rg-tbl st-tbl">
            <thead><tr><th>Data</th><th>Nr.</th><th>Ce s-a numărat</th><th className="num">Materiale</th><th>Stare</th><th /></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} className={d.status === 'ciorna' ? 'st-draft-r' : ''}>
                  <td className="num">{dmy(d.doc_date)}</td>
                  <td><b>{d.nr || '—'}</b></td>
                  <td>{d.note || 'tot stocul'}</td>
                  <td className="num">{d.lines}</td>
                  <td><span className={`st-pill ${d.status === 'ciorna' ? 'warn' : 'ok'}`}>{d.status_label}</span><small>{d.actor}</small></td>
                  <td className="st-act-c"><button type="button" className="rg-btn sm" onClick={() => setOpen(d.id)}>
                    {d.status === 'ciorna' ? <><Icon name="pen" /> Continuă</> : <><Icon name="eye" /> Deschide</>}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** Что считать: весь склад или категории; «în program» сервер ставит в строки сам. */
function Start({ list, onCancel, onMade }: { list: ListData; onCancel: () => void; onMade: (id: number) => void }) {
  const [pick, setPick] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const live = list.items.filter((x) => x.active)
  const cats = [...new Set(live.map((x) => x.cat || 'Fără categorie'))]
  async function start() {
    setBusy(true)
    try {
      const r = await stockApi.createDoc({ kind: 'inventar', cats: pick, note: pick.join(', ') })
      onMade(r.data.id)
    } catch (e) { setErr(asApiError(e).text || 'Nu s-a început.') } finally { setBusy(false) }
  }
  return (
    <div className="fcard st-inv">
      <div className="rg-bar">
        <span className="rg-ttl"><b>Inventariere nouă</b><small>ce numărați acum?</small></span>
        <button type="button" className="rg-btn" onClick={onCancel}><Icon name="chev-l" /> Înapoi</button>
      </div>
      <div className="st-inv-b">
        <div className="rg-chips" role="group" aria-label="Ce se numără">
          <button type="button" className={`rg-chip${pick.length === 0 ? ' on' : ''}`} aria-pressed={pick.length === 0} onClick={() => setPick([])}>Tot stocul <small>{live.length}</small></button>
          {cats.map((c) => (
            <button key={c} type="button" className={`rg-chip${pick.includes(c) ? ' on' : ''}`} aria-pressed={pick.includes(c)}
              onClick={() => setPick(pick.includes(c) ? pick.filter((x) => x !== c) : [...pick, c])}>
              {c} <small>{live.filter((x) => (x.cat || 'Fără categorie') === c).length}</small>
            </button>
          ))}
        </div>
        <p className="hint">Numărați ce e pe raft. Ce nu ați numărat rămâne cum e în program; ciorna se poate continua altă zi.</p>
        {err && <p className="st-err" role="alert">{err}</p>}
      </div>
      <div className="rg-dlg-f st-foot">
        <button type="button" className="dp-btn pri" disabled={busy} onClick={() => { void start() }}><Icon name="check" /> Începe numărarea</button>
      </div>
    </div>
  )
}

function Sheet({ id, list, onDone }: { id: number; list: ListData; onDone: () => void }) {
  const { navigate } = useStockCtx()
  const load = useCallback((signal: AbortSignal) => stockApi.doc(id, signal), [id])
  const { state, retry } = useLoad<DocData>(load, navigate)
  if (state.status === 'failed') return <LoadFailed error={state.error} onRetry={retry} />
  if (state.status !== 'ready') return <div className="fcard st-inv" aria-busy="true" />
  return <Count doc={state.data.doc} list={list} onDone={onDone} />
}

const plain = (milli: number) => num(milli, 3).split('.').join('')

function Count({ doc, list, onDone }: { doc: Doc; list: ListData; onDone: () => void }) {
  const { say, refresh } = useStockCtx()
  const money = list.can.money
  const ro = doc.status !== 'ciorna'
  const [shelf, setShelf] = useState<Record<number, string>>(() =>
    Object.fromEntries(doc.lines.map((l) => [l.id, l.qty_milli == null ? '' : plain(l.qty_milli)])))
  const [diffOnly, setDiffOnly] = useState(ro)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const avgOf = (iid: number) => list.items.find((x) => x.id === iid)?.avg_bani ?? 0
  const rowsAll = doc.lines.map((l) => {
    const prog = l.prog_milli ?? 0
    const v = parseQty(shelf[l.id] ?? '')
    const diff = ro ? l.diff_milli ?? null : Number.isNaN(v) ? null : v - prog
    return { l, prog, diff, val: diff === null ? 0 : Math.round((diff / 1000) * (l.avg_bani ?? avgOf(l.item_id))) }
  })
  const rows = diffOnly ? rowsAll.filter((r) => r.diff) : rowsAll
  const done = rowsAll.filter((r) => r.diff !== null).length
  const diffs = rowsAll.filter((r) => r.diff)
  const bad = rowsAll.some((r) => (shelf[r.l.id] ?? '').trim() && Number.isNaN(parseQty(shelf[r.l.id]!)))

  function body() {
    return { lines: doc.lines.map((l) => {
      const v = parseQty(shelf[l.id] ?? '')
      return { id: l.id, item_id: l.item_id, qty_milli: Number.isNaN(v) ? null : v }
    }) }
  }
  async function save(final: boolean) {
    if (bad) { setErr('„Pe raft” — un număr, ex. 12 sau 3,8.'); return }
    if (final) {
      const skip = rowsAll.length - done
      const text = `${diffs.length === 0 ? 'Nicio diferență' : diffs.length === 1 ? '1 material va fi corectat' : `${diffs.length} materiale vor fi corectate`}`
        + (skip ? `; ${skip} nenumărate rămân cum sunt în program` : '') + '. Aplicați inventarierea?'
      if (!(await ask({ text, ok: 'Aplică' }))) return
    }
    setBusy(true)
    try {
      await stockApi.saveDoc(doc.id, body())
      if (final) await stockApi.closeDoc(doc.id)
      refresh()
      say(final ? `Inventarierea ${doc.nr} aplicată: ${diffs.length} corecții în mișcări.` : 'Ciorna inventarierii salvată — se poate continua altă zi.')
      onDone()
    } catch (e) { setErr(asApiError(e).text || 'Nu s-a salvat.') } finally { setBusy(false) }
  }
  async function drop() {
    if (!(await ask({ text: `Ștergeți ciorna inventarierii ${doc.nr}? Stocul nu se schimbă.`, danger: true, ok: 'Șterge' }))) return
    try { await stockApi.dropDoc(doc.id); refresh(); say('Ciorna ștearsă.'); onDone() } catch (e) { setErr(asApiError(e).text || 'Nu s-a șters.') }
  }

  return (
    <div className="fcard st-inv">
      <div className="rg-bar">
        <span className="rg-ttl"><b>Inventarierea {doc.nr} · {dmy(doc.doc_date)}</b>
          <small>{ro ? `${doc.status_label} ${dmy(doc.closed_at)} · ${doc.actor}` : `numărate ${done} din ${rowsAll.length}`} · {doc.note || 'tot stocul'}</small></span>
        <span className="st-qrow">
          <label className="st-chk"><input type="checkbox" checked={diffOnly} onChange={(e) => setDiffOnly(e.target.checked)} /> doar cu diferențe</label>
          {!ro && <button type="button" className="rg-btn sm" onClick={() => setShelf((s) => Object.fromEntries(doc.lines.map((l) => [l.id, (s[l.id] ?? '').trim() ? s[l.id]! : plain(l.prog_milli ?? 0)])))}>
            Restul — ca în program</button>}
          <button type="button" className="rg-btn" onClick={onDone}><Icon name="chev-l" /> Toate inventarierile</button>
        </span>
      </div>
      <div className="rg-scroll">
        <table className="rg-tbl st-tbl st-count">
          <thead><tr><th>Material</th><th className="num">În program</th><th>Pe raft</th><th className="num">Diferența</th>{money && <th className="num">Valoare</th>}</tr></thead>
          <tbody>
            {rows.map(({ l, prog, diff, val }) => (
              <tr key={l.id} className={diff ? (diff < 0 ? 'st-neg-r' : 'st-plus-r') : ''}>
                <td><b>{l.item}</b><small>{list.items.find((x) => x.id === l.item_id)?.pack_name ?? ''}</small></td>
                <td className="num">{qtyText(prog, l.unit)}</td>
                <td>{ro ? (l.qty_milli == null ? <span className="st-mute">nenumărat</span> : qtyText(l.qty_milli, l.unit)) : (
                  <span className="st-qrow"><input className="dp-fld st-n" inputMode="decimal" value={shelf[l.id] ?? ''} placeholder="?" aria-label={`Pe raft: ${l.item}`}
                    onChange={(e) => { setShelf({ ...shelf, [l.id]: e.target.value }); setErr('') }} /><small className="st-mute">{l.unit}</small></span>
                )}</td>
                <td className="num">{diff === null ? <span className="st-mute">—</span> : diff === 0 ? <span className="st-mute">0</span>
                  : <span className={`st-q ${diff > 0 ? 'in' : 'out'}`}>{diff > 0 ? '+' : '-'}{num(Math.abs(diff))} {l.unit}</span>}</td>
                {money && <td className="num">{diff ? lei(Math.abs(val)) : '—'}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <p className="hint rg-none">{ro ? 'Pe raft era exact cât în program — nicio corecție.' : 'Nicio diferență până acum.'}</p>}
      {err && <p className="st-err st-pad" role="alert">{err}</p>}
      {!ro && (
        <div className="rg-dlg-f st-foot">
          {money && diffs.length > 0 && <span className="st-total">Diferențe: <b>{lei(diffs.reduce((s, r) => s + r.val, 0))}</b></span>}
          <button type="button" className="dp-btn ghost" onClick={() => { void drop() }}><Icon name="trash" /> Șterge ciorna</button>
          <button type="button" className="dp-btn" disabled={busy} onClick={() => { void save(false) }}><Icon name="save" /> Salvează ciorna</button>
          <button type="button" className="dp-btn pri" disabled={busy || !done} onClick={() => { void save(true) }}><Icon name="check" /> Aplică</button>
        </div>
      )}
    </div>
  )
}
