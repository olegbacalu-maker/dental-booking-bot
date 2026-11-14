import { useEffect, useRef, useState, type ReactNode } from 'react'
import { AppLink } from '../../components/AppLink'
import { hideDialog, showDialog } from '../../components/dialog'
import { Icon } from '../../components/Icon'
import { asApiError } from '../../services/api'
import {
  dmy, guess, labApi, money, teethOf,
  type Act, type FormData, type FormPlan, type Impression, type Item, type OrderBody, type OrderData, type OrderRow,
} from './lab'
import { StatusPill, TeethGrid } from './parts'

interface Line extends Item { key: number }

interface Draft {
  lines: Line[]
  active: number
  doctor: string
  lab: number
  labName: string
  sent: string
  due: string
  dueTouched: boolean
  urgent: boolean
  impression: Impression
  note: string
}

let seq = 0
const lineOf = (p: FormPlan | null): Line => {
  const g = p ? guess(p.procedure) : { work: '', material: '' }
  return { key: ++seq, plan_item_id: p?.id ?? null, plan: p ? { id: p.id, procedure: p.procedure, tooth: p.tooth, status: p.status } : null,
    work: g.work, material: g.material, shade: '', teeth: p ? teethOf(p.tooth, p.procedure) : [], qty: 1, grp: null, price_bani: null }
}

function fresh(f: FormData, planItem: number | null): Draft {
  const p = f.plan.find((x) => x.id === planItem) ?? null
  const first = lineOf(p)
  return { lines: [first], active: first.key, doctor: p?.doctor_id || f.doctor_id, lab: f.labs[0]?.id ?? 0, labName: '',
    sent: f.today, due: '', dueTouched: false, urgent: false, impression: '', note: '' }
}

function of(d: OrderData): Draft {
  const o = d.order
  const lines = o.items.map((it) => ({ ...it, key: ++seq }))
  return { lines, active: lines[0]?.key ?? 0, doctor: o.doctor_id, lab: o.lab_id ?? 0, labName: '', sent: o.sent_on, due: o.due_on,
    dueTouched: true, urgent: o.urgent, impression: o.impression, note: o.note }
}

const lei = (b: number | null | undefined) => (b == null ? '' : String(b / 100))
const toBani = (s: string): number | null => (s.trim() === '' ? null : Math.round(Number(s.replace(',', '.')) * 100))

/** Окно заказа: новый (из плана или из списка) или открытый — тогда с шагами и историей. */
export function OrderDialog({ form, data, planItem, busy, onClose, onCreated, onSaved, onPrint, onAct }: {
  form: FormData
  data: OrderData | null
  planItem: number | null
  busy: boolean
  onClose: () => void
  onCreated: (id: number, text: string, print: boolean) => void
  onSaved: (text: string) => void
  onPrint: (id: number) => void
  onAct: (o: OrderRow, a: Act) => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const can = data?.can ?? form.can
  const [d, setD] = useState<Draft>(() => (data ? of(data) : fresh(form, planItem)))
  const [field, setField] = useState('')
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)
  const [adding, setAdding] = useState(false)
  useEffect(() => { showDialog(ref.current) }, [])
  const up = (p: Partial<Draft>) => setD((x) => ({ ...x, ...p }))
  const upLine = (key: number, p: Partial<Line>) => setD((x) => ({ ...x, lines: x.lines.map((l) => (l.key === key ? { ...l, ...p } : l)) }))
  const addLine = (p: FormPlan | null) => { setAdding(false); setD((x) => { const l = lineOf(p); return { ...x, lines: [...x.lines, l], active: l.key } }) }
  const line = d.lines.find((l) => l.key === d.active) ?? d.lines[0]!
  const idx = d.lines.indexOf(line)
  const order = data?.order ?? null
  const closed = order ? order.status === 'finalizat' || order.status === 'anulat' : false
  const labs = form.labs
  const noLabs = labs.length === 0 && !(order && order.lab_id)
  const typing = noLabs || d.lab === -1
  const free = form.plan.filter((p) => !p.ordered && !d.lines.some((l) => l.plan_item_id === p.id))
  const last = can.money && d.lab > 0
    ? form.last_prices?.find((x) => x.lab_id === d.lab && x.work.toLowerCase() === line.work.trim().toLowerCase()) : undefined
  const bad = (k: string) => field === k || field.startsWith(`${k}.`)
  const lineBad = (i: number) => field.startsWith(`items.${i}.`)

  /* срок по рабочим дням лаборатории — считает сервер */
  useEffect(() => {
    if (d.dueTouched || d.lab <= 0 || !d.sent) return
    const ctl = new AbortController()
    labApi.due(d.lab, d.sent, ctl.signal).then((r) => setD((x) => (x.dueTouched ? x : { ...x, due: r.data.due_on })), () => { /* срок — руками */ })
    return () => ctl.abort()
  }, [d.lab, d.sent, d.dueTouched])

  async function save(print: boolean) {
    setErr('')
    setField('')
    const body: OrderBody = {
      lab_id: typing ? null : d.lab || null,
      lab_name: typing ? d.labName.trim() : '',
      doctor_id: d.doctor,
      ...(order ? {} : { sent_on: d.sent }),
      ...(d.due ? { due_on: d.due } : {}),
      urgent: d.urgent,
      impression: d.impression,
      note: d.note.trim(),
      items: d.lines.map((l) => {
        const it: Item = { plan_item_id: l.plan_item_id, work: l.work.trim(), material: l.material.trim(), shade: l.shade.trim(),
          teeth: l.teeth, qty: l.qty, grp: l.grp, ...(l.id ? { id: l.id } : {}) }
        return can.money ? { ...it, price_bani: l.price_bani ?? null } : it
      }),
    }
    setSaving(true)
    try {
      if (order) {
        const r = await labApi.save(order.id, body)
        onSaved(r.text)
        if (print) onPrint(order.id)
        else hideDialog(ref.current)
      } else {
        const r = await labApi.create({ pid: form.patient!.pid, ...body })
        hideDialog(ref.current)
        onCreated(r.data.id, r.text, print)
      }
    } catch (e) {
      const a = asApiError(e)
      setErr(a.text || 'Comanda nu s-a salvat.')
      setField(a.field ?? '')
      const m = /^items\.(\d+)\./.exec(a.field ?? '')
      const hit = m ? d.lines[Number(m[1])] : undefined
      if (hit) up({ active: hit.key })
    } finally {
      setSaving(false)
    }
  }

  const who = order ? order.patient : form.patient?.name ?? ''
  const off = closed || saving || busy
  return (
    <dialog ref={ref} className="rg-dlg wide lb-dlg" onClose={onClose} aria-label="Comandă la laborator">
      <div className="dlg-head">
        <span><Icon name="box" /> {order ? `Comanda nr. ${order.nr}` : 'Comandă nouă la laborator'}</span>
        <button type="button" className="rg-x" onClick={() => hideDialog(ref.current)} aria-label="Închide"><Icon name="close" /></button>
      </div>
      <div className="rg-dlg-b">
        <p className="lb-who">
          <b>{who}</b><small> · fișa {order?.fisa ?? form.patient?.fisa}</small>
          {order && <StatusPill o={order} />}
        </p>
        {data && data.steps.length > 0 && (
          <div className="lb-steps-box" role="group" aria-label="Pasul următor">
            {data.steps.filter((s) => s.act !== 'undo' && s.act !== 'cancel').map((s) => (
              <button key={s.act} type="button" className={`lb-go${s.main ? ' fin' : ' alt'}`} disabled={busy} onClick={() => onAct(order!, s.act)}>
                {s.label}</button>
            ))}
          </div>
        )}
        {d.lines.length > 1 && (
          <div className="lb-lines" role="tablist" aria-label="Lucrări">
            {d.lines.map((l, i) => (
              <div key={l.key} className={`lb-line${l.key === d.active ? ' on' : ''}${lineBad(i) ? ' bad' : ''}`}>
                <button type="button" role="tab" aria-selected={l.key === d.active} onClick={() => up({ active: l.key })}>
                  <b>{i + 1}. {l.work || 'lucrare'}</b>
                  <small>{[l.teeth.join(', '), l.material, l.shade].filter(Boolean).join(' · ') || '—'}</small>
                </button>
                {!closed && (
                  <button type="button" className="lb-ib" aria-label={`Scoate lucrarea ${i + 1}`}
                    onClick={() => setD((x) => { const lines = x.lines.filter((y) => y.key !== l.key); return { ...x, lines, active: lines[0]!.key } })}>
                    <Icon name="close" /></button>
                )}
              </div>
            ))}
          </div>
        )}
        {line.plan && <p className="hint dp-m0">Din plan: <b>{line.plan.tooth ? `${line.plan.tooth} · ` : ''}{line.plan.procedure}</b></p>}
        <F label="Dinți (formula FDI)" hint="Apăsați dinții. Pentru proteze și alignere pot rămâne neapăsați." bad={field === `items.${idx}.teeth`}>
          <TeethGrid value={line.teeth} onPick={closed ? undefined : (n) => upLine(line.key, { teeth: line.teeth.includes(n) ? line.teeth.filter((x) => x !== n) : [...line.teeth, n].sort((a, b) => a - b) })} />
        </F>
        <div className="lb-three">
          <F label="Lucrarea" bad={field === `items.${idx}.work`}>
            <input className="dp-fld" list="lb-works" value={line.work} maxLength={120} disabled={closed} placeholder="ex. Coroană"
              onChange={(e) => upLine(line.key, { work: e.target.value })} />
          </F>
          <F label="Material">
            <input className="dp-fld" list="lb-materials" value={line.material} maxLength={120} disabled={closed}
              onChange={(e) => upLine(line.key, { material: e.target.value })} />
          </F>
          <F label="Bucăți" bad={field === `items.${idx}.qty`}>
            <input className="dp-fld lb-qty" inputMode="numeric" value={line.qty} disabled={closed}
              onChange={(e) => upLine(line.key, { qty: Math.min(99, Math.max(1, Number(e.target.value.replace(/\D/g, '').slice(0, 2)) || 1)) })} />
          </F>
        </div>
        <datalist id="lb-works">{form.works.map((w) => <option key={w} value={w} />)}</datalist>
        <datalist id="lb-materials">{form.materials.map((w) => <option key={w} value={w} />)}</datalist>
        <F label="Culoare">
          <div className="rg-chips lb-shades">
            {form.shades.map((s) => (
              <button key={s} type="button" className={`rg-chip${line.shade === s ? ' on' : ''}`} disabled={closed}
                aria-pressed={line.shade === s} onClick={() => upLine(line.key, { shade: line.shade === s ? '' : s })}>{s}</button>
            ))}
          </div>
          <input className="dp-fld" placeholder="sau în cuvinte: A2 la colet, A1 incizal" maxLength={120} aria-label="Culoare în cuvinte" disabled={closed}
            value={form.shades.includes(line.shade) ? '' : line.shade} onChange={(e) => upLine(line.key, { shade: e.target.value })} />
        </F>
        {can.money && (
          <F label="Preț laborator, MDL" bad={field === `items.${idx}.price`}
            hint={`${line.qty > 1 ? 'pentru toate bucățile · ' : ''}${last ? `ultima dată la acest laborator: ${money(last.price_bani)} MDL (nr. ${last.nr})` : 'nu apare pe fișa de comandă'}`}>
            <input className="dp-fld lb-price" inputMode="decimal" value={lei(line.price_bani)} placeholder={last ? money(last.price_bani) : '—'} disabled={closed}
              onChange={(e) => upLine(line.key, { price_bani: toBani(e.target.value.replace(/[^\d.,]/g, '').slice(0, 9)) })} />
          </F>
        )}
        {!closed && (
          <div className="lb-addline">
            {!adding && (
              <button type="button" className="lnk" onClick={() => (free.length ? setAdding(true) : addLine(null))}>
                <Icon name="plus" /> încă o lucrare în aceeași comandă</button>
            )}
            {adding && (
              <div className="rg-chips">
                {free.map((p) => (
                  <button key={p.id} type="button" className="rg-chip" onClick={() => addLine(p)}>{p.tooth ? <b>{p.tooth}</b> : null} {p.procedure}</button>
                ))}
                <button type="button" className="rg-chip" onClick={() => addLine(null)}><Icon name="plus" /> fără poziție în plan</button>
              </div>
            )}
          </div>
        )}

        <hr className="lb-hr" />
        {noLabs ? (
          can.labs ? (
            <div className={`lb-newlab${bad('lab') ? ' bad' : ''}`}>
              <p className="hint dp-m0"><Icon name="info" /> Lista laboratoarelor e încă goală. Scrieți laboratorul aici — se adaugă în
                {' '}<AppLink href="/admin/settings/lab">Setări › Laboratoare</AppLink> și data viitoare se alege din listă.</p>
              <F label="Laboratorul"><input className="dp-fld" value={d.labName} maxLength={120} placeholder="ex. Dental Lab"
                onChange={(e) => up({ labName: e.target.value })} /></F>
            </div>
          ) : (
            <p className="lb-err-box">Lista laboratoarelor e goală. Laboratoarele le adaugă recepția în Setări › Laboratoare.</p>
          )
        ) : (
          <F label="Laboratorul" bad={bad('lab')}>
            <div className="rg-chips">
              {order && order.lab_id && !labs.some((l) => l.id === order.lab_id) && (
                <button type="button" className={`rg-chip${d.lab === order.lab_id ? ' on' : ''}`} disabled={closed} onClick={() => up({ lab: order.lab_id! })}>{order.lab}</button>
              )}
              {labs.map((l) => (
                <button key={l.id} type="button" className={`rg-chip${d.lab === l.id ? ' on' : ''}`} disabled={closed} aria-pressed={d.lab === l.id}
                  onClick={() => up({ lab: l.id })}>{l.name} <small>{l.days} zile lucr.</small></button>
              ))}
              {can.labs && !closed && (
                <button type="button" className={`rg-chip${d.lab === -1 ? ' on' : ''}`} onClick={() => up({ lab: -1 })}><Icon name="plus" /> Alt laborator</button>
              )}
            </div>
            {d.lab === -1 && (
              <input className="dp-fld lb-mt" value={d.labName} maxLength={120} placeholder="Numele laboratorului" aria-label="Numele laboratorului"
                onChange={(e) => up({ labName: e.target.value })} />
            )}
          </F>
        )}
        <div className="lb-three">
          <F label="Medic" bad={bad('doctor')}>
            <select className="dp-sel" value={d.doctor} disabled={closed} onChange={(e) => up({ doctor: e.target.value })}>
              <option value="">—</option>
              {form.doctors.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
              {order && order.doctor_id && !form.doctors.some((x) => x.id === order.doctor_id) && <option value={order.doctor_id}>{order.doctor}</option>}
            </select>
          </F>
          <F label="Trimis" bad={bad('sent_on')}>
            {/* дата отправки — шаг истории: после сохранения сервер её не меняет */}
            <input className="dp-fld" type="date" value={d.sent} max={form.today} disabled={closed || order !== null} onChange={(e) => up({ sent: e.target.value })} />
          </F>
          <F label="Termen de la laborator" bad={bad('due_on')} hint={d.dueTouched ? '' : d.due ? 'după zilele lucrătoare ale laboratorului' : 'gol — îl socotește programul după laborator'}>
            <input className="dp-fld" type="date" value={d.due} min={d.sent} disabled={closed} onChange={(e) => up({ due: e.target.value, dueTouched: true })} />
          </F>
        </div>
        <div className="lb-two">
          <F label="Amprenta">
            <div className="rg-chips">
              {Object.entries(form.words.impression).filter(([k]) => k).map(([k, label]) => (
                <button key={k} type="button" className={`rg-chip sm${d.impression === k ? ' on' : ''}`} disabled={closed} aria-pressed={d.impression === k}
                  onClick={() => up({ impression: (d.impression === k ? '' : k) as Impression })}>{label}</button>
              ))}
            </div>
          </F>
          <label className="lb-check"><input type="checkbox" checked={d.urgent} disabled={closed} onChange={(e) => up({ urgent: e.target.checked })} />
            <b>Urgent</b> <small>— se tipărește mare pe fișă</small></label>
        </div>
        <F label="Indicații pentru tehnician" bad={bad('note')}>
          <textarea className="dp-fld" rows={2} maxLength={1000} value={d.note} disabled={closed} onChange={(e) => up({ note: e.target.value })}
            placeholder="ex. umăr ceramic vestibular, contact strâns cu 25, implant Osstem 4.5" />
        </F>
        <p className="lb-195"><Icon name="shield" /> Pe fișa de comandă pleacă {form.who === 'fisa' ? 'numărul fișei' : 'numele pacientului'}, medicul,
          lucrările, dinții, culoarea și termenul — fără anamneză, date de contact și preț (Legea 195). Fiecare tipărire se notează în istoric.</p>
        {order && <History data={data!} busy={busy} onAct={onAct} />}
        {err && <p className="lb-err-box" role="alert">{err}</p>}
      </div>
      <div className="rg-dlg-f">
        {order && <button type="button" className="dp-btn" onClick={() => onPrint(order.id)}><Icon name="print" /> Fișa de comandă</button>}
        {!closed && (
          <>
            <button type="button" className="dp-btn" disabled={off} onClick={() => { void save(false) }}><Icon name="save" /> Salvează</button>
            <button type="button" className="dp-btn pri" disabled={off} onClick={() => { void save(true) }}>
              <Icon name="print" /> {order ? 'Salvează și tipărește' : 'Trimite și tipărește fișa'}</button>
          </>
        )}
        {closed && <button type="button" className="dp-btn pri" onClick={() => hideDialog(ref.current)}>Închide</button>}
      </div>
    </dialog>
  )
}

function F({ label, hint, bad, children }: { label: string; hint?: string; bad?: boolean; children: ReactNode }) {
  return (
    <div className={`rg-f${bad ? ' lb-bad' : ''}`}>
      <span className="rg-fl">{label}</span>
      {children}
      {hint && <small className="hint">{hint}</small>}
    </div>
  )
}

function History({ data, busy, onAct }: { data: OrderData; busy: boolean; onAct: (o: OrderRow, a: Act) => void }) {
  const o = data.order
  const undo = data.steps.find((s) => s.act === 'undo')
  const cancel = data.steps.find((s) => s.act === 'cancel')
  return (
    <div className="rg-f">
      <span className="rg-fl lb-hist-h">Istoric
        <span>
          {undo && <button type="button" className="lnk" disabled={busy} onClick={() => onAct(o, 'undo')}><Icon name="undo" /> {undo.label}</button>}
          {cancel && <button type="button" className="lnk lb-red" disabled={busy} onClick={() => onAct(o, 'cancel')}><Icon name="ban" /> {cancel.label}</button>}
        </span>
      </span>
      <ol className="lb-hist">
        {o.events.map((e) => (
          <li key={e.id} data-k={e.kind} className={e.undone ? 'undone' : undefined}>
            <b>{dmy(e.on_date)}</b> {e.kind_label}
            {e.due_on && <small> · termen {dmy(e.due_on)}</small>}
            {e.cause_label && <small> · {e.cause_label}</small>}
            {e.payer_label && <small> · plătește: {e.payer_label.toLowerCase()}</small>}
            {e.note && <small> — {e.note}</small>}
            {(e.doer || e.actor) && <small className="lb-who-s"> · {e.doer || e.actor}</small>}
          </li>
        ))}
      </ol>
    </div>
  )
}
