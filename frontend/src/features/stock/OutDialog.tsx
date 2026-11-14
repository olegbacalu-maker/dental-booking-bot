import { useEffect, useRef, useState } from 'react'
import { hideDialog, showDialog } from '../../components/dialog'
import { Icon } from '../../components/Icon'
import { api, asApiError } from '../../services/api'
import { dmy, num, packWord, parseQty, qtyText, REASONS, stockApi, type Item, type Reason } from './stock'
import { F } from './parts'
import { useStockCtx } from './StockScreen'

interface Pat { id: number; name: string }

/** Ручное списание с причиной; у дорогого — на пациента и с лотом. Минус не запрещён: остаток станет красным. */
export function OutDialog({ item, onClose }: { item: number; onClose: () => void }) {
  const { say, refresh, list } = useStockCtx()
  const ref = useRef<HTMLDialogElement>(null)
  const live = (list?.items ?? []).filter((x) => x.active)
  const [picked, setPicked] = useState<Item | null>(() => live.find((x) => x.id === item) ?? null)
  const it = picked
  const [qty, setQty] = useState(it?.costly || it?.bulk ? '1' : '')
  const [inPacks, setInPacks] = useState(false)
  const [reason, setReason] = useState<Reason | ''>(it ? (it.costly ? 'pacient' : it.bulk ? 'deschis' : '') : '')
  const [pat, setPat] = useState<Pat | null>(null)
  const [lot, setLot] = useState('')
  const [note, setNote] = useState('')
  const [find, setFind] = useState('')
  const [pats, setPats] = useState<Pat[]>([])
  const [bad, setBad] = useState<{ field: string; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { showDialog(ref.current); const r = ref.current; return () => hideDialog(r) }, [])
  useEffect(() => {
    if (reason !== 'pacient') return
    const ctl = new AbortController()
    const t = window.setTimeout(() => {
      api.get<{ rows: Pat[] }>(`/patients${find.trim() ? `?q=${encodeURIComponent(find.trim())}` : ''}`, { signal: ctl.signal })
        .then((r) => setPats(r.data.rows.slice(0, 8))).catch(() => { /* поиск пациента — подсказка, не ошибка окна */ })
    }, 200)
    return () => { window.clearTimeout(t); ctl.abort() }
  }, [reason, find])

  const raw = parseQty(qty)
  const milli = it && !Number.isNaN(raw) ? (inPacks ? Math.round((raw / 1000) * it.pack_qty_milli) : raw) : NaN
  const after = it && !Number.isNaN(milli) ? it.qty_milli - milli : null
  const lots = it?.lots.filter((x) => x.lot) ?? []

  function pick(nid: number) {
    const n = live.find((x) => x.id === nid) ?? null
    setPicked(n)
    setReason(n?.costly ? 'pacient' : n?.bulk ? 'deschis' : '')
    setQty(n?.costly || n?.bulk ? '1' : '')
    setLot(''); setInPacks(false); setBad(null)
  }

  async function save() {
    if (!it) { setBad({ field: 'item_id', text: 'Alegeți materialul.' }); return }
    if (Number.isNaN(milli) || milli <= 0) { setBad({ field: 'qty_milli', text: 'Un număr mai mare ca zero.' }); return }
    if (!reason) { setBad({ field: 'reason', text: 'Alegeți motivul.' }); return }
    if (reason === 'pacient' && !pat) { setBad({ field: 'pid', text: 'Alegeți pacientul.' }); return }
    if (reason === 'altul' && !note.trim()) { setBad({ field: 'note', text: 'Scrieți ce s-a întâmplat.' }); return }
    setBusy(true)
    try {
      const r = await stockApi.out({ item_id: it.id, qty_milli: milli, reason, note: note.trim(),
        ...(reason === 'pacient' && pat ? { pid: pat.id } : {}), ...(lot ? { lot } : {}) })
      refresh()
      const neg = r.data.neg
      say(`${it.name}: -${qtyText(milli, it.unit)}${neg ? ' — stocul a intrat pe minus' : ''}.`, neg ? 'warn' : 'ok')
      onClose()
    } catch (e) {
      const err = asApiError(e)
      setBad({ field: err.field ?? '', text: err.text || 'Nu s-a scăzut.' })
    } finally {
      setBusy(false)
    }
  }
  const b = (f: string) => (bad && bad.field === f ? bad.text : undefined)

  return (
    <dialog ref={ref} className="rg-dlg st-dlg" onClose={onClose} aria-label="Scoate din stoc">
      <div className="dlg-head">
        <span><Icon name="minus" /> Scoate din stoc</span>
        <button type="button" className="rg-x" onClick={onClose} aria-label="Închide"><Icon name="close" /></button>
      </div>
      <div className="rg-dlg-b">
        {bad && !['item_id', 'qty_milli', 'reason', 'pid', 'note'].includes(bad.field) && <p className="st-err" role="alert">{bad.text}</p>}
        <F label="Materialul" bad={b('item_id')}>
          {item && it ? <b className="st-pickd">{it.name} <small>{it.pack_name}</small></b> : (
            <select className="dp-sel" value={it?.id ?? 0} onChange={(e) => pick(Number(e.target.value))} autoFocus aria-label="Materialul">
              <option value={0}>— alegeți —</option>
              {live.map((x) => <option key={x.id} value={x.id}>{x.name} · {x.cat}</option>)}
            </select>
          )}
        </F>
        {it && (
          <>
            <F label="Cât" bad={b('qty_milli')}
              hint={<>Pe raft acum: <b>{qtyText(it.qty_milli, it.unit)}</b>{after !== null && <> · rămâne <b className={after < 0 ? 'st-neg' : ''}>{qtyText(after, it.unit)}</b></>}</>}>
              <div className="st-qrow">
                <input className="dp-fld st-n" inputMode="decimal" value={qty} onChange={(e) => { setQty(e.target.value); setBad(null) }} autoFocus={!!item} aria-label="Cantitatea" />
                {it.pack_qty_milli > 1000 ? (
                  <span className="dp-seg st-seg" role="group" aria-label="Unitatea">
                    <button type="button" className={inPacks ? '' : 'on'} onClick={() => setInPacks(false)}>{it.unit}</button>
                    <button type="button" className={inPacks ? 'on' : ''} onClick={() => setInPacks(true)}>{packWord(it)} ({num(it.pack_qty_milli)} {it.unit})</button>
                  </span>
                ) : <span className="st-mute">{it.unit}</span>}
              </div>
            </F>
            {after !== null && after < 0 && (
              <p className="st-note warn"><Icon name="info" /> Stocul intră pe minus. Se poate: de obicei factura încă nu e introdusă. Minusul dispare
                la următoarea intrare sau la inventariere.</p>
            )}
            <F label="Motivul" bad={b('reason')}>
              <div className="rg-chips" role="group" aria-label="Motivul">
                {REASONS.map(([k, label]) => (
                  <button key={k} type="button" className={`rg-chip sm${reason === k ? ' on' : ''}`} aria-pressed={reason === k} onClick={() => { setReason(k); setBad(null) }}>{label}</button>
                ))}
              </div>
            </F>
            {reason === 'pacient' && (
              <F label="Pacientul" bad={b('pid')} hint={it.costly ? 'lotul ajunge în fișa pacientului (rechemarea unui lot de implanturi)' : undefined}>
                {pat ? (
                  <span className="st-qrow"><b>{pat.name}</b><button type="button" className="dp-link" onClick={() => setPat(null)}>altul</button></span>
                ) : (
                  <>
                    <input className="dp-fld" placeholder="Numele pacientului" value={find} onChange={(e) => setFind(e.target.value)} aria-label="Caută pacientul" />
                    <div className="rg-chips">
                      {pats.map((p) => <button key={p.id} type="button" className="rg-chip sm" onClick={() => { setPat(p); setBad(null) }}>{p.name}</button>)}
                    </div>
                  </>
                )}
              </F>
            )}
            {(it.costly || lots.length > 0) && (
              <F label="Lotul" hint={lots.length ? undefined : 'pe raft nu e niciun lot înregistrat — scrieți-l de pe ambalaj'}>
                {lots.length > 0 ? (
                  <div className="rg-chips" role="group" aria-label="Lotul">
                    {lots.map((x) => (
                      <button key={x.lot} type="button" className={`rg-chip sm${lot === x.lot ? ' on' : ''}`} aria-pressed={lot === x.lot} onClick={() => setLot(lot === x.lot ? '' : x.lot)}>
                        {x.lot} <small>{x.exp_on ? `până la ${dmy(x.exp_on)}` : ''} · {qtyText(x.qty_milli, it.unit)}</small>
                      </button>
                    ))}
                  </div>
                ) : <input className="dp-fld" value={lot} maxLength={40} onChange={(e) => setLot(e.target.value)} placeholder="nr. lot" aria-label="Lot" />}
              </F>
            )}
            <F label={reason === 'altul' ? 'Notă (ce s-a întâmplat)' : 'Notă (opțional)'} bad={b('note')}><input className="dp-fld" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} placeholder="ex. seringă fisurată la livrare" /></F>
          </>
        )}
      </div>
      <div className="rg-dlg-f">
        <button type="button" className="dp-btn" onClick={onClose}>Renunță</button>
        <button type="button" className="dp-btn pri" disabled={busy} onClick={() => { void save() }}><Icon name="minus" /> Scoate din stoc</button>
      </div>
    </dialog>
  )
}
