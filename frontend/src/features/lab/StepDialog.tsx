import { useEffect, useRef, useState } from 'react'
import { hideDialog, showDialog } from '../../components/dialog'
import { Icon } from '../../components/Icon'
import { labApi, type OrderRow, type Words } from './lab'

export type StepKind = 'etapa' | 'refacere' | 'cancel'

const HEAD: Record<StepKind, [string, Parameters<typeof Icon>[0]['name'], string]> = {
  etapa: ['Etapa următoare la laborator', 'undo', 'Trimite la etapa următoare'],
  refacere: ['Refacere — lucrarea are defecte', 'excl', 'Trimite la refacere'],
  cancel: ['Anulează comanda', 'ban', 'Anulează comanda'],
}

/* После примерки работа уходит технику двумя разными путями: обычный
   следующий этап и переделка брака с причиной и плательщиком. Их держат
   раздельно, иначе нет отчёта о переделках и неясно, кто платит. */
export function StepDialog({ o, kind, words, onClose, onDone }: {
  o: OrderRow
  kind: StepKind
  words: Words | null
  onClose: () => void
  onDone: (b: { due_on: string; cause: string; payer: string; note: string }) => Promise<string | null>
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const [w, setW] = useState<Words | null>(words)
  const [due, setDue] = useState('')
  const [cause, setCause] = useState('')
  const [payer, setPayer] = useState('')
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const [field, setField] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { showDialog(ref.current) }, [])
  /* слова причин и плательщиков — с сервера; из строки списка окна заказа нет */
  useEffect(() => {
    if (w || kind !== 'refacere') return
    const ctl = new AbortController()
    labApi.form(null, null, ctl.signal).then((r) => setW(r.data.words), () => { /* без слов — коды */ })
    return () => ctl.abort()
  }, [w, kind])
  const [title, icon, go] = HEAD[kind]

  async function send() {
    setErr('')
    setField('')
    if (kind === 'cancel' && !note.trim()) { setField('why'); return }
    setBusy(true)
    const fail = await onDone({ due_on: due, cause, payer, note: note.trim() })
    setBusy(false)
    if (fail) setErr(fail)
    else hideDialog(ref.current)
  }

  const chips = (dict: Record<string, string> | undefined, value: string, set: (v: string) => void) => (
    <div className="rg-chips">
      {Object.entries(dict ?? {}).map(([k, label]) => (
        <button key={k} type="button" className={`rg-chip${value === k ? ' on' : ''}`} aria-pressed={value === k} onClick={() => set(k)}>{label}</button>
      ))}
    </div>
  )

  return (
    <dialog ref={ref} className="rg-dlg lb-dlg" onClose={onClose} aria-label={title}>
      <div className="dlg-head"><span><Icon name={icon} /> {title}</span>
        <button type="button" className="rg-x" onClick={() => hideDialog(ref.current)} aria-label="Închide"><Icon name="close" /></button></div>
      <div className="rg-dlg-b">
        <p className="lb-who"><b>{o.patient}</b><small> · nr. {o.nr} · {o.work}{kind === 'etapa' ? ` · etapa ${o.stage + 1}` : ''}</small></p>
        {kind === 'etapa' && <p className="hint dp-m0">Proba a trecut, lucrarea pleacă la următoarea etapă (de ex. după carcasă — ceramica).</p>}
        {kind === 'refacere' && (
          <>
            <div className={`rg-f${field === 'cause' ? ' lb-bad' : ''}`}><span className="rg-fl">Ce nu e bine</span>{chips(w?.cause, cause, setCause)}</div>
            <div className={`rg-f${field === 'payer' ? ' lb-bad' : ''}`}><span className="rg-fl">Cine plătește refacerea</span>{chips(w?.payer, payer, setPayer)}</div>
          </>
        )}
        <div className={`rg-f${field === 'why' || field === 'note' ? ' lb-bad' : ''}`}>
          <span className="rg-fl">{kind === 'cancel' ? 'De ce se anulează' : kind === 'refacere' ? 'Detalii pentru tehnician' : 'Indicații (opțional)'}</span>
          <textarea className="dp-fld" rows={2} maxLength={300} value={note} onChange={(e) => setNote(e.target.value)}
            placeholder={kind === 'cancel' ? 'ex. pacientul a amânat tratamentul' : kind === 'refacere'
              ? 'ex. contact ocluzal înalt pe 46; culoarea mai deschisă cu o nuanță' : 'ex. carcasa a trecut, ceramica A2'} />
          {kind === 'cancel' && <small className="hint">Comanda nu se șterge: rămâne în istoric cu numărul ei.</small>}
        </div>
        {kind !== 'cancel' && (
          <div className="rg-f"><span className="rg-fl">Termen nou</span>
            <input className="dp-fld lb-date" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
            <small className="hint">Gol — după zilele lucrătoare ale laboratorului.</small>
          </div>
        )}
        {err && <p className="lb-err-box" role="alert">{err}</p>}
      </div>
      <div className="rg-dlg-f">
        <button type="button" className="dp-btn" onClick={() => hideDialog(ref.current)}>Renunță</button>
        <button type="button" className={`dp-btn pri${kind === 'cancel' ? ' lb-danger' : ''}`} disabled={busy} onClick={() => { void send() }}>
          <Icon name={icon} /> {go}</button>
      </div>
    </dialog>
  )
}
