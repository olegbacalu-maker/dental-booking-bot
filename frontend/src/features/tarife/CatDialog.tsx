import { useEffect, useRef, useState } from 'react'
import { hideDialog, showDialog, useDialogLeave } from '../../components/dialog'
import { Icon } from '../../components/Icon'

/** Имя категории: новая («+ Categorie») или переименование. Запись — у хозяина; отказ он возвращает текстом. */
export function CatDialog({ name, max, onSave, onClose }: {
  /** null — новая категория */
  name: string | null
  max: number
  onSave: (name: string) => Promise<string | null>
  onClose: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const { leave } = useDialogLeave(ref, onClose)
  const [v, setV] = useState(name ?? '')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { showDialog(ref.current); const r = ref.current; return () => hideDialog(r) }, [])
  const title = name === null ? 'Categorie nouă' : 'Redenumește categoria'

  async function save() {
    const n = v.trim()
    if (!n) { setErr('Scrieți numele categoriei.'); return }
    if (n === name) { leave(); return }
    setBusy(true)
    const bad = await onSave(n)
    setBusy(false)
    if (bad === null) leave()
    else setErr(bad)
  }

  return (
    <dialog ref={ref} className="rg-dlg tf-dlg" onClose={leave} aria-label={title}>
      <div className="dlg-head">
        <span><Icon name="folder" /> {title}</span>
        <button type="button" className="rg-x" onClick={leave} aria-label="Închide"><Icon name="close" /></button>
      </div>
      <form className="rg-dlg-b" onSubmit={(e) => { e.preventDefault(); void save() }}>
        <label className="tf-fld">
          <span>Numele categoriei</span>
          <input className={`dp-fld${err ? ' bad' : ''}`} value={v} maxLength={max} autoFocus placeholder="ex. Terapie"
            onChange={(e) => { setV(e.target.value); setErr('') }} />
        </label>
        <p className="st-err" role="alert">{err}</p>
      </form>
      <div className="rg-dlg-f">
        <button type="button" className="dp-btn" onClick={leave}>Renunță</button>
        <button type="button" className="dp-btn pri" disabled={busy} onClick={() => { void save() }}><Icon name="save" /> Salvează</button>
      </div>
    </dialog>
  )
}
