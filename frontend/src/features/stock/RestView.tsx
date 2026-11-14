import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { Icon } from '../../components/Icon'
import { asApiError } from '../../services/api'
import { ItemDialog } from './ItemDialog'
import { lei, MATERIALE, num, packWord, qtyText, stockApi, type Filter, type Item, type ListData } from './stock'
import { Empty, Exp, Flags, Rest } from './parts'
import { useStockCtx } from './StockScreen'
import { roCount } from '../../utils/plural'

const FILTERS: [Filter, string][] = [['all', 'Toate'], ['low', 'Sub prag'], ['exp', 'Expiră curând'], ['arh', 'Arhivă']]

/** Остатки: каталог по категориям, порог, срок; дешёвое — плитками «Consumabile diverse» под таблицей. */
export function RestView({ data, f, cat, find }: { data: ListData | null; f: Filter; cat: string; find: string }) {
  const { say, refresh, out, go } = useStockCtx()
  const [q, setQ] = useSearchParams()
  const [typed, setTyped] = useState(find)
  const [edit, setEdit] = useState<{ id: number; k: number } | null>(null)
  const [busy, setBusy] = useState(0)
  const [undo, setUndo] = useState<{ id: number; name: string } | null>(null)
  /* «Deschis» без окна: ошибку щелчка чинит «Anulează» 10 секунд, потом — инвентаризация */
  useEffect(() => {
    if (!undo) return
    const t = window.setTimeout(() => setUndo(null), UNDO_MS)
    return () => window.clearTimeout(t)
  }, [undo])
  if (!data) return <div className="fcard rg-body" aria-busy="true" />
  const money = data.can.money
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(q)
    if (v) p.set(k, v)
    else p.delete(k)
    setQ(p, { replace: true })
  }

  if (data.items.length === 0) {
    return (
      <>
        <Empty title="Stocul e încă gol">
          <p className="hint">Începeți cu lista materialelor pe care le aveți: din Excel (catalogul și resturile de pe raft deodată)
            sau câte unul. Apoi fiecare factură de la furnizor adaugă, iar scoaterile și inventarierea scad.</p>
          <div className="st-row">
            <button type="button" className="rg-btn pri" onClick={() => go('import')}><Icon name="upload" /> Importă din Excel</button>
            <button type="button" className="rg-btn" onClick={() => setEdit({ id: 0, k: Date.now() })}><Icon name="plus" /> Adaugă un material</button>
            <button type="button" className="rg-btn" onClick={() => go('intrari', { doc: 'nou' })}><Icon name="download" /> Prima factură</button>
          </div>
          <p className="hint">Mănușile, rulourile de vată și alte lucruri ieftine nu se numără pe bucată: le treceți în
            „Consumabile diverse” și scădeți un pachet când îl deschideți.</p>
        </Empty>
        {edit && <ItemDialog key={edit.k} id={edit.id} onClose={() => setEdit(null)} />}
      </>
    )
  }

  const needle = find.toLowerCase()
  const pool = data.items.filter((it) => (f === 'arh' ? !it.active : it.active)
    && (!cat || (it.cat || 'Fără categorie') === cat)
    && (!needle || `${it.name} ${it.cat} ${it.supplier} ${it.data.code ?? ''}`.toLowerCase().includes(needle))
    && (f === 'low' ? it.low : f === 'exp' ? it.soon || it.expired : true))
  const rank = (c: string) => { const i = data.cats.indexOf(c); return i < 0 ? data.cats.length : i }
  const sorted = [...pool].sort((a, b) => rank(a.cat) - rank(b.cat) || a.cat.localeCompare(b.cat) || Number(b.neg) - Number(a.neg) || a.name.localeCompare(b.name))
  const rows = sorted.filter((it) => !it.bulk)
  const bulk = sorted.filter((it) => it.bulk)
  const value = pool.reduce((s, it) => s + (it.value_bani ?? 0), 0)
  const counts: Record<Filter, number> = { all: data.counts.all, low: data.counts.low, exp: data.counts.soon + data.counts.expired, arh: data.counts.archive }

  async function opened(it: Item) {
    setBusy(it.id)
    try {
      const r = await stockApi.open(it.id)
      refresh()
      setUndo({ id: r.data.id, name: `${it.name}: -1 ${packWord(it)} (deschis)${r.data.neg ? ' — pe minus' : ''}` })
    } catch (e) {
      say(asApiError(e).text || 'Nu s-a putut scădea.', 'err')
    } finally {
      setBusy(0)
    }
  }

  async function cancel() {
    if (!undo) return
    const u = undo
    setUndo(null)
    try {
      await stockApi.undo(u.id)
      refresh()
      say('Anulat — restul e ca înainte.')
    } catch (e) {
      say(asApiError(e).text || 'Nu se mai poate anula: faceți o corecție la inventariere.', 'warn')
    }
  }

  return (
    <>
      {undo && (
        <div className="st-undo" role="status">
          <Icon name="check" /><span>{undo.name}</span>
          <button type="button" className="rg-btn sm" onClick={() => { void cancel() }}><Icon name="undo" /> Anulează</button>
        </div>
      )}
      <div className="fcard st-bar">
        <form className="st-qrow" role="search" onSubmit={(e) => { e.preventDefault(); set('q', typed.trim()) }}>
          <input className="dp-fld st-find" placeholder="Caută material, furnizor" value={typed} onChange={(e) => setTyped(e.target.value)}
            onBlur={() => { if (typed.trim() !== find) set('q', typed.trim()) }} aria-label="Caută" />
        </form>
        <span className="dp-seg st-seg" role="group" aria-label="Filtru">
          {FILTERS.map(([k, label]) => (
            <button key={k} type="button" className={f === k ? 'on' : ''} aria-pressed={f === k} onClick={() => set('f', k === 'all' ? '' : k)}>
              {label} <small>{counts[k]}</small>
            </button>
          ))}
        </span>
        <button type="button" className="rg-btn st-push" onClick={() => setEdit({ id: 0, k: Date.now() })}><Icon name="plus" /> Material nou</button>
      </div>

      <div className="fcard rg-body">
        {rows.length > 0 && (
          <div className="rg-scroll">
            <table className="rg-tbl st-tbl">
              <thead>
                <tr><th>Material</th><th>Rest</th><th>Prag</th><th>Valabil până la</th>{money && <th className="num">Valoare</th>}<th /></tr>
              </thead>
              <tbody>
                {rows.map((it, i) => {
                  const head = !cat && (i === 0 || rows[i - 1]!.cat !== it.cat)
                  return [
                    head && <tr key={`c-${it.cat}`} className="st-cat-r"><td colSpan={money ? 6 : 5}>{it.cat}</td></tr>,
                    <tr key={it.id} className={it.neg ? 'st-neg-r' : it.low ? 'st-low-r' : ''} data-id={it.id}>
                      <td className="st-name">
                        <button type="button" className="st-lnk" onClick={() => setEdit({ id: it.id, k: Date.now() })}><b>{it.name}</b></button>
                        <small>{[it.pack_name, it.supplier, it.data.raft].filter(Boolean).join(' · ')}</small>
                        <Flags it={it} />
                      </td>
                      <td><Rest it={it} /></td>
                      <td className="num">{it.min_milli === null ? <span className="st-mute">—</span>
                        : <>{qtyText(it.min_milli, it.unit)}{it.pack_qty_milli > 1000 && <small>~{num((it.min_milli / it.pack_qty_milli) * 1000, 1)} {packWord(it)}</small>}</>}</td>
                      <td><Exp it={it} /></td>
                      {money && <td className="num">{it.value_bani ? lei(it.value_bani) : '—'}{it.avg_bani ? <small>{lei(it.avg_bani)} / {it.unit}</small> : null}</td>}
                      <td className="st-act-c">
                        {it.active && <button type="button" className="rg-btn sm" onClick={() => out(it.id)}><Icon name="minus" /> Scade</button>}
                        <button type="button" className="rg-ib" aria-label={`Fișa materialului ${it.name}`} title="Fișa materialului" onClick={() => setEdit({ id: it.id, k: Date.now() })}><Icon name="pen" /></button>
                      </td>
                    </tr>,
                  ]
                })}
              </tbody>
            </table>
          </div>
        )}
        {rows.length === 0 && bulk.length === 0 && <p className="hint rg-none">Nimic în acest filtru.</p>}
        <p className="hint rg-foot"><Icon name="info" />
          {roCount(pool.length, MATERIALE)}{cat ? ` în „${cat}”` : ''}{money ? ` · valoarea stocului ${lei(value)} (la prețul mediu de intrare)` : ''}.
          Restul nu se scrie de mână: îl schimbă facturile, scoaterile și inventarierea.
        </p>
      </div>

      {bulk.length > 0 && (
        <div className="fcard st-bulk">
          <div className="st-bulk-h">
            <b><Icon name="box" /> Consumabile diverse</b>
            <small className="hint">nu se numără pe bucată: la deschiderea unui pachet nou — „Deschis”. Restul arată câte pachete întregi mai sunt.</small>
          </div>
          <div className="st-tiles">
            {bulk.map((it) => (
              <div key={it.id} className={`st-tile${it.neg ? ' neg' : it.low ? ' low' : ''}`} data-id={it.id}>
                <button type="button" className="st-tile-n" onClick={() => setEdit({ id: it.id, k: Date.now() })}><b>{it.name}</b><small>{it.pack_name}</small></button>
                <span className="st-tile-q"><span><b>{num(it.qty_milli)}</b> {it.unit}</span>{it.min_milli !== null && <small>prag {num(it.min_milli)}</small>}</span>
                {it.active && (
                  <button type="button" className="rg-btn sm" disabled={busy === it.id} title={`Scade 1 ${it.unit}`} onClick={() => { void opened(it) }}>
                    <Icon name="minus" /> Deschis
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      {edit && <ItemDialog key={edit.k} id={edit.id} onClose={() => setEdit(null)} />}
    </>
  )
}

const UNDO_MS = 10_000
