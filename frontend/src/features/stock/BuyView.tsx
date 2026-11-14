import { useCallback, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { useLoad } from '../../hooks/useLoad'
import { asApiError } from '../../services/api'
import { roCount } from '../../utils/plural'
import { buyPrintHref, dmy, lei, MATERIALE, orderState, qtyText, stockApi, type BuyData } from './stock'
import { Empty } from './parts'
import { useBindRetry, useStockCtx } from './StockScreen'

/** «De cumpărat»: ниже порога по поставщикам; «Comandat» — лёгкая отметка, чтобы не заказать дважды (не заказ). */
export function BuyView() {
  const { navigate, say, refresh } = useStockCtx()
  const load = useCallback((signal: AbortSignal) => stockApi.buy(signal), [])
  const { state, retry } = useLoad<BuyData>(load, navigate)
  useBindRetry(retry)
  const [n, setN] = useState<Record<number, string>>({})
  const [off, setOff] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  if (state.status === 'failed') return <LoadFailed error={state.error} onRetry={retry} />
  if (state.status !== 'ready') return <div className="fcard rg-body" aria-busy="true" />
  const { groups, counts, can, prefs } = state.data
  if (!counts.low) {
    return (
      <Empty ico="check" title="Nimic sub prag">
        <p className="hint">Când restul unui material cu prag scade sub el, materialul apare aici, grupat pe furnizori — gata de tipărit.</p>
      </Empty>
    )
  }
  const packs = (id: number, def: number) => { const v = n[id]; return v === undefined ? def : Math.max(0, Number(v) || 0) }

  async function act(run: () => Promise<unknown>, ok: string) {
    setBusy(true)
    try { await run(); refresh(); say(ok) } catch (e) { say(asApiError(e).text || 'Nu s-a salvat.', 'err') } finally { setBusy(false) }
  }

  const all = groups.flatMap((g) => g.rows)
  const printed = all.filter((r) => !off.includes(r.item_id) && orderState(r.ordered) !== 'on').map((r) => ({ id: r.item_id, packs: packs(r.item_id, r.buy_packs) }))
  const total = all.filter((r) => !off.includes(r.item_id) && orderState(r.ordered) !== 'on').reduce((s, r) => s + (r.est_bani ?? 0) * (packs(r.item_id, r.buy_packs) / Math.max(1, r.buy_packs)), 0)
  return (
    <div className="fcard rg-body">
      <div className="rg-bar">
        <span className="rg-ttl">
          <b>De cumpărat · {roCount(counts.low, MATERIALE)} sub prag{counts.ordered - counts.late > 0 && <span className="st-mute"> · din care comandate: {counts.ordered - counts.late}</span>}</b>
          <small>propunerea aduce restul la dublul pragului, în ambalaje întregi; „Comandat” e doar o notă — dispare singură la factura materialului</small>
        </span>
        <AppLink className="rg-btn" href={buyPrintHref(printed)}><Icon name="print" /> Tipărește</AppLink>
      </div>
      {groups.map((g) => {
        const open = g.rows.filter((r) => orderState(r.ordered) !== 'on' && !off.includes(r.item_id))
        return (
          <div key={g.supplier_id ?? 0} className="st-buy-g">
            <div className="st-buy-h">
              <b>{g.supplier}</b>{g.phone && <small><Icon name="phone" /> {g.phone}</small>}{g.email && <small><Icon name="mail" /> {g.email}</small>}
              {open.length > 1 && (
                <button type="button" className="rg-btn sm st-push" disabled={busy}
                  onClick={() => { void act(() => stockApi.order(open.map((r) => r.item_id)), `${g.supplier}: ${roCount(open.length, MATERIALE)} notate „comandat”.`) }}>
                  <Icon name="check" /> Comandat tot ({open.length})
                </button>
              )}
            </div>
            <div className="rg-scroll">
              <table className="rg-tbl st-tbl">
                <thead><tr><th /><th>Material</th><th className="num">Rest</th><th className="num">Prag</th><th>De cumpărat</th>{can.money && <th className="num">Estimat</th>}<th /></tr></thead>
                <tbody>
                  {g.rows.map((r) => {
                    const st = orderState(r.ordered)
                    const on = !off.includes(r.item_id) && st !== 'on'
                    const k = packs(r.item_id, r.buy_packs)
                    return (
                      <tr key={r.item_id} className={st === 'on' ? 'st-ord-r' : on ? '' : 'st-off-r'} data-ord={st}>
                        <td className="st-chk-c">{st !== 'on' && <input type="checkbox" checked={on} aria-label={`În listă: ${r.name}`}
                          onChange={() => setOff(on ? [...off, r.item_id] : off.filter((x) => x !== r.item_id))} />}</td>
                        <td><b>{r.name}</b><small>{r.pack_name}</small>
                          {r.ordered && st === 'on' && <span className="st-pill mute st-ord"><Icon name="check" /> comandat {dmy(r.ordered.on).slice(0, 5)} · {r.ordered.by}</span>}
                          {r.ordered && st === 'late' && <span className="st-pill warn st-ord"><Icon name="hourglass" /> comandat acum {r.ordered.days} zile, n-a venit</span>}
                        </td>
                        <td className={`num${r.neg ? ' st-neg' : ''}`}>{qtyText(r.qty_milli, r.unit)}</td>
                        <td className="num">{qtyText(r.min_milli, r.unit)}</td>
                        <td>{st === 'on' ? <span className="st-mute">—</span> : (
                          <span className="st-qrow"><input className="dp-fld st-n sm" inputMode="numeric" value={n[r.item_id] ?? String(r.buy_packs)} aria-label={`Ambalaje: ${r.name}`}
                            onChange={(e) => setN({ ...n, [r.item_id]: e.target.value.replace(/\D/g, '').slice(0, 4) })} /><small className="st-mute">× {r.pack_name || r.unit}</small></span>
                        )}</td>
                        {can.money && <td className="num">{st === 'on' || !r.est_bani ? '—' : lei(Math.round(r.est_bani * (k / Math.max(1, r.buy_packs))))}</td>}
                        <td className="st-act-c">
                          {st === 'none' && <button type="button" className="rg-btn sm" disabled={busy} onClick={() => { void act(() => stockApi.order([r.item_id]), `${r.name}: notat „comandat”.`) }}><Icon name="check" /> Comandat</button>}
                          {st === 'late' && <button type="button" className="rg-btn sm" disabled={busy} onClick={() => { void act(() => stockApi.order([r.item_id]), `${r.name}: comandat din nou azi.`) }}><Icon name="refresh" /> Comandat din nou</button>}
                          {st !== 'none' && <button type="button" className="dp-link" disabled={busy} onClick={() => { void act(() => stockApi.unorder(r.item_id), `${r.name}: nota „comandat” anulată.`) }}>Anulează</button>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )
      })}
      <p className="hint rg-foot"><Icon name="info" /> Lista nu e o comandă: după ce marfa vine, se introduce factura, materialul iese singur din listă
        și nota „comandat” dispare. Fără factură {prefs.order_days} zile — nota se stinge cu „n-a venit”.
        {can.money && total > 0 ? ` Estimat la prețul mediu (fără cele comandate): ${lei(Math.round(total))}.` : ''}</p>
    </div>
  )
}
