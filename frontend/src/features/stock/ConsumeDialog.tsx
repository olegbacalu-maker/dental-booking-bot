import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { hideDialog, showDialog } from '../../components/dialog'
import { Icon } from '../../components/Icon'
import { asApiError } from '../../services/api'
import { dmy, num, parseQty, qtyText, stockApi, type PlanProposal } from './stock'

interface Row { on: boolean; qty: string; lot: string }
interface Target { id: number; what: string }

const plain = (milli: number) => num(milli, 3).split('.').join('')

/** Режим «cu confirmare»: после «Finalizată» — материалы из техкарты; количество правится, лишнее снимается галочкой,
 *  у дорогого — лот с остатком. «Fără scădere» — тоже решение: позиция больше не ждёт подтверждения. */
export function ConsumeDialog({ target, data, onClose, onDone }: {
  target: Target; data: PlanProposal; onClose: () => void; onDone: (text: string, tone?: 'ok' | 'warn') => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const [rows, setRows] = useState<Row[]>(() => data.lines.map((l) => ({ on: l.on, qty: plain(l.qty_milli), lot: l.lot ?? '' })))
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { showDialog(ref.current); const r = ref.current; return () => hideDialog(r) }, [])
  const up = (i: number, p: Partial<Row>) => { setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...p } : r))); setErr('') }

  async function confirm() {
    const picked = rows.map((r, i) => ({ r, l: data.lines[i]! })).filter(({ r }) => r.on)
    if (picked.some(({ r }) => !(parseQty(r.qty) > 0))) { setErr('Cantitatea — un număr mai mare ca zero, ex. 0,3.'); return }
    setBusy(true)
    try {
      const res = await stockApi.planConsume(target.id,
        picked.map(({ r, l }) => ({ item_id: l.item_id, qty_milli: parseQty(r.qty), ...(r.lot ? { lot: r.lot } : {}) })))
      onDone(res.text || `S-au scăzut ${picked.length === 1 ? '1 material' : `${picked.length} materiale`} din stoc.`, res.data.neg?.length ? 'warn' : 'ok')
      onClose()
    } catch (e) { setErr(asApiError(e).text || 'Nu s-a scăzut.') } finally { setBusy(false) }
  }
  async function skip() {
    setBusy(true)
    try {
      const res = await stockApi.planSkip(target.id)
      onDone(res.text || 'Finalizată fără scădere din stoc.', 'warn')
      onClose()
    } catch (e) { setErr(asApiError(e).text || 'Nu s-a salvat.') } finally { setBusy(false) }
  }

  return (
    <div className="rg st st-host">
      <dialog ref={ref} className="rg-dlg wide st-dlg st-cons" onClose={onClose} aria-label="Materiale consumate">
        <div className="dlg-head">
          <span><Icon name="box" /> Materiale consumate</span>
          <button type="button" className="rg-x" onClick={onClose} aria-label="Închide"><Icon name="close" /></button>
        </div>
        <div className="rg-dlg-b">
          <p className="st-cons-who"><b>{target.what}</b><small>după fișa serviciului „{data.plan.service}”{data.plan.doctor ? ` · ${data.plan.doctor}` : ''} — corectați cât s-a folosit de fapt</small></p>
          <table className="st-tc">
            <thead><tr><th /><th>Material</th><th>Cantitate</th><th>Lot</th><th className="num">Pe raft</th></tr></thead>
            <tbody>
              {data.lines.map((l, i) => {
                const r = rows[i]!
                const q = parseQty(r.qty)
                const after = r.on && q > 0 ? l.stock_milli - q : l.stock_milli
                return (
                  <tr key={l.item_id} className={r.on ? '' : 'st-off-r'}>
                    <td className="st-tc-c"><input type="checkbox" checked={r.on} aria-label={`Se scade: ${l.item}`} onChange={(e) => up(i, { on: e.target.checked })} /></td>
                    <td><b>{l.item}</b>{l.optional && <small className="st-mute">opțional</small>}{!l.active && <small className="st-warnt">în arhivă</small>}</td>
                    <td><span className="st-qrow"><input className="dp-fld st-n" inputMode="decimal" value={r.qty} disabled={!r.on} aria-label={`Cantitatea: ${l.item}`}
                      onChange={(e) => up(i, { qty: e.target.value })} /><small className="st-mute">{l.unit}</small></span></td>
                    <td>{l.costly ? (l.lots.length ? (
                      <span className="rg-chips" role="group" aria-label={`Lotul: ${l.item}`}>
                        {l.lots.map((x) => (
                          <button key={x.lot || 'fara'} type="button" className={`rg-chip sm${r.lot === x.lot ? ' on' : ''}`} aria-pressed={r.lot === x.lot}
                            disabled={!r.on} onClick={() => up(i, { lot: r.lot === x.lot ? '' : x.lot })}>
                            {x.lot || 'fără lot'} <small>{x.exp_on ? `${dmy(x.exp_on)} · ` : ''}{qtyText(x.qty_milli, l.unit)}</small>
                          </button>
                        ))}
                      </span>
                    ) : <input className="dp-fld st-lot" value={r.lot} maxLength={60} placeholder="nr. lot" disabled={!r.on} aria-label={`Lot: ${l.item}`}
                      onChange={(e) => up(i, { lot: e.target.value })} />) : <span className="st-mute">—</span>}</td>
                    <td className="num">{qtyText(l.stock_milli, l.unit)}{r.on && q > 0 && <small className={after < 0 ? 'st-errt' : 'st-mute'}>rămâne {qtyText(after, l.unit)}</small>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {rows.some((r, i) => r.on && data.lines[i]!.stock_milli - (parseQty(r.qty) || 0) < 0) && (
            <p className="st-note warn"><Icon name="info" /> Unele materiale intră pe minus. Se poate: probabil factura încă nu e introdusă.</p>
          )}
          {err && <p className="st-err" role="alert">{err}</p>}
        </div>
        <div className="rg-dlg-f">
          <button type="button" className="dp-btn ghost" disabled={busy} onClick={() => { void skip() }}>Fără scădere</button>
          <button type="button" className="dp-btn pri" disabled={busy} onClick={() => { void confirm() }}><Icon name="check" /> Confirmă</button>
        </div>
      </dialog>
    </div>
  )
}

/** Хозяин окна у фиши. После «Finalizată» спрашивает склад о позиции; `pending` — открывает окно. Позиции, окно которых
 *  закрыли без решения, ждут значком «Materiale de confirmat» в строке плана (список — из загрузчика фиши). */
export function useConsume(say: (text: string, tone: 'ok' | 'warn' | 'err') => void, loaded: number[] | null | undefined) {
  const [open, setOpen] = useState<{ t: Target; data: PlanProposal; k: number } | null>(null)
  const [base, setBase] = useState(loaded)
  const [pending, setPending] = useState<number[]>(loaded ?? [])
  if (loaded !== undefined && loaded !== base) {
    setBase(loaded)
    setPending(loaded ?? [])
  }
  const ask = useCallback((t: Target) => {
    stockApi.planProposal(t.id).then((r) => {
      const d = r.data
      if (d.state === 'pending' && d.lines.length) {
        setPending((p) => (p.includes(t.id) ? p : [...p, t.id]))
        setOpen({ t, data: d, k: Date.now() })
      } else {
        setPending((p) => p.filter((x) => x !== t.id))
      }
    }).catch(() => { /* склад недоступен — позиция уже закрыта, окно не обязательно */ })
  }, [])
  const afterFinal = useCallback((t: Target & { service: string | null }) => { if (t.service) ask(t) }, [ask])
  /** Позиция ушла из «finalizat» (Redeschide): возврат делает сервер, ждать подтверждения нечего. */
  const reopened = useCallback((id: number) => setPending((p) => p.filter((x) => x !== id)), [])
  const chip = (t: Target): ReactNode => (pending.includes(t.id)
    ? <button type="button" className="st-cons-chip" onClick={() => ask(t)}><Icon name="box" /> Materiale de confirmat</button> : null)
  const node = open ? (
    <ConsumeDialog key={open.k} target={open.t} data={open.data} onClose={() => setOpen(null)}
      onDone={(text, tone) => { setPending((p) => p.filter((x) => x !== open.t.id)); say(text, tone ?? 'ok') }} />
  ) : null
  return { afterFinal, reopened, chip, node }
}
