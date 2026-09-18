import { useEffect, useRef } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import { ToothForm } from './ToothForm'
import type { Odontogram, ToothSave } from './chart'

/* Диалог зуба компактной карточки фиши: та же форма, что у инспектора
   детальной страницы, плюс история зуба под ней. */
const T = {
  tooth: 'Dinte',
  history: 'Istoria dintelui',
  close: 'Închide',
} as const

interface Props {
  model: Odontogram
  n: number | null
  busy: boolean
  formKey: string
  sel: string
  onSel: (letter: string) => void
  onSave: (n: number, body: ToothSave) => void
  onClose: () => void
}

export function ToothDialog({ model, n, busy, formKey, sel, onSel, onSave, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    if (n !== null) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [n])
  const info = n !== null ? model.teeth[String(n)] : undefined
  const hist = n !== null ? (model.history[String(n)] ?? []) : []
  return (
    <dialog ref={ref} onClose={onClose}>
      <div className="dlg-head">
        <span>{T.tooth} {n ?? ''}</span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      {info && n !== null && (
        <ToothForm key={formKey} model={model} n={n} info={info} busy={busy} sel={sel} onSel={onSel} onSave={onSave} />
      )}
      <div className="thist">
        {hist.length > 0 && (
          <>
            <div className="th-t">{T.history}</div>
            {hist.map((h, i) => <div key={i} className="th-r"><span>{h.at}</span>{h.text}</div>)}
          </>
        )}
      </div>
    </dialog>
  )
}
