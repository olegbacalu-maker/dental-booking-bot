import { useCallback, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { useLoad } from '../../hooks/useLoad'
import { asApiError } from '../../services/api'
import { dmy, lei, movesXlsxHref, stockApi, type Move, type MovesData } from './stock'
import { Empty, KindPill, Signed } from './parts'
import { useBindRetry, useStockCtx } from './StockScreen'

const shift = (day: string, n: number) => {
  const d = new Date(`${day}T12:00:00`)
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}

/** Журнал движений: остаток — сумма этих строк; ошибка правится новой строкой, не правкой старой. */
export function JournalView() {
  const { navigate, list, say, refresh } = useStockCtx()
  const today = list?.today ?? new Date().toISOString().slice(0, 10)
  const [item, setItem] = useState(0)
  const [kind, setKind] = useState('')
  const [from, setFrom] = useState(shift(today, -30))
  const [to, setTo] = useState(today)
  const [actor, setActor] = useState('')
  const [sup, setSup] = useState(0)
  const load = useCallback((signal: AbortSignal) => stockApi.moves({ item, kind, from, to, actor, supplier: sup }, signal), [item, kind, from, to, actor, sup])
  const { state, retry } = useLoad<MovesData>(load, navigate)
  useBindRetry(retry)
  const reset = () => { setItem(0); setKind(''); setFrom(shift(today, -30)); setTo(today); setActor(''); setSup(0) }
  const words = list?.words.kinds ?? {}

  async function undo(m: Move) {
    if (!(await ask({ text: `Anulați „${m.kind_label}: ${m.item}”? Se scrie o corecție inversă; rândul rămâne în istorie.`, ok: 'Anulează' }))) return
    try {
      await stockApi.undo(m.id)
      refresh()
      say('Mișcarea anulată.')
    } catch (e) { say(asApiError(e).text || 'Nu se poate anula.', 'err') }
  }

  if (state.status === 'failed') return <LoadFailed error={state.error} onRetry={retry} />
  const data = state.status === 'ready' ? state.data : null
  if (data && !data.moves.length && !item && !kind && !actor && !sup && (list?.items.length ?? 0) === 0) {
    return (
      <Empty ico="clipboard" title="Încă nu e nicio mișcare">
        <p className="hint">Aici se adună tot ce schimbă stocul: intrările din facturi, scoaterile (pe pacient, expirate, defecte),
          diferențele de la inventariere. Restul fiecărui material este suma acestor rânduri.</p>
      </Empty>
    )
  }
  const money = data?.can.money ?? false
  const sum = (data?.moves ?? []).reduce((s, m) => s + (m.cost_bani ?? 0), 0)
  return (
    <div className="fcard rg-body" aria-busy={state.status === 'loading' || undefined}>
      <div className="st-filters">
        <select className="dp-sel" value={item} onChange={(e) => setItem(Number(e.target.value))} aria-label="Materialul">
          <option value={0}>Toate materialele</option>
          {(list?.items ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select>
        <select className="dp-sel" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Tipul">
          <option value="">Toate tipurile</option>
          {Object.entries(words).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
        <span className="st-qrow st-period"><input className="dp-fld st-date" type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} aria-label="De la" />
          <span className="st-mute">–</span><input className="dp-fld st-date" type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} aria-label="Până la" /></span>
        <select className="dp-sel" value={actor} onChange={(e) => setActor(e.target.value)} aria-label="Cine">
          <option value="">Toți</option>
          {(data?.actors ?? []).map((a) => <option key={a}>{a}</option>)}
        </select>
        {(list?.suppliers.length ?? 0) > 0 && (
          <select className="dp-sel" value={sup} onChange={(e) => setSup(Number(e.target.value))} aria-label="Furnizorul">
            <option value={0}>Toți furnizorii</option>
            {list!.suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        )}
        <button type="button" className="dp-link" onClick={reset}>Resetează</button>
        <AppLink className="rg-btn sm st-push" href={movesXlsxHref(to.slice(0, 7))} download title="Mișcările lunii, fără pacienți — pentru contabil">
          <Icon name="download" /> Excel pentru contabil</AppLink>
      </div>
      {data && data.moves.length > 0 && (
        <div className="rg-scroll">
          <table className="rg-tbl st-tbl st-jr">
            <thead><tr><th>Data</th><th>Tipul</th><th>Material</th><th className="num">Cantitate</th>{money && <th className="num">Valoare</th>}<th>Document / motiv</th><th>Pacient</th><th>Cine</th><th /></tr></thead>
            <tbody>
              {data.moves.map((m) => {
                const what = m.doc ? `${m.doc.kind === 'factura' ? 'Factura' : m.doc.kind === 'inventar' ? 'Inventarierea' : 'Import'} ${m.doc.nr}${m.doc.supplier ? ` · ${m.doc.supplier}` : ''}` : m.reason_label
                return (
                  <tr key={m.id} className={m.undone ? 'st-off-r' : ''}>
                    <td className="num">{dmy(m.on)}<small>{m.at.slice(11, 16)}</small></td>
                    <td><KindPill m={m} /></td>
                    <td><b>{m.item}</b>{m.lot && <small>lot {m.lot}</small>}</td>
                    <td className="num">{m.qty_milli ? <Signed q={m.qty_milli} unit={m.unit} /> : <span className="st-mute">—</span>}</td>
                    {money && <td className="num">{m.cost_bani == null ? '—' : lei(Math.abs(m.cost_bani))}</td>}
                    <td>{what || '—'}{m.note && <small>{m.note}</small>}{m.undone && <small className="st-warnt">anulată</small>}</td>
                    <td>{m.pid ? <AppLink href={`/admin/patient/${m.pid}`}>{m.patient}</AppLink> : <span className="st-mute">—</span>}</td>
                    <td>{m.actor}{m.source === 'import' && <small>din Excel</small>}</td>
                    <td className="st-act-c">{m.undoable && <button type="button" className="rg-btn sm" onClick={() => { void undo(m) }}><Icon name="undo" /> Anulează</button>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {data && data.moves.length === 0 && <p className="hint rg-none">Nicio mișcare cu aceste filtre.</p>}
      {data && data.moves.length > 0 && (
        <p className="hint rg-foot"><Icon name="info" /> {data.moves.length}{data.more ? '+' : ''} mișcări{money ? ` · sold valoric ${sum >= 0 ? '+' : '-'}${lei(Math.abs(sum))}` : ''}.
          {data.more ? ' Lista e scurtată — strângeți perioada.' : ''} Rândurile nu se șterg și nu se rescriu: o greșeală se îndreaptă cu un rând nou.</p>
      )}
    </div>
  )
}
