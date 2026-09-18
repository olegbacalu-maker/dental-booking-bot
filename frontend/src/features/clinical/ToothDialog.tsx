import { useEffect, useRef } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import { ToothForm } from './ToothForm'
import type { Odontogram } from './chart'
import type { ToothDraft } from './useChart'

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
  sel: string
  onSel: (letter: string) => void
  draft: ToothDraft | null
  dirty: boolean
  onEdit: (patch: Partial<ToothDraft>) => void
  onSave: () => void
  onDiscard: () => void
  onClose: () => void
}

export function ToothDialog({ model, n, busy, sel, onSel, draft, dirty, onEdit, onSave, onDiscard, onClose }: Props) {
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
      {info && n !== null && draft && (
        <ToothForm
          model={model}
          n={n}
          info={info}
          busy={busy}
          sel={sel}
          onSel={onSel}
          draft={draft}
          dirty={dirty}
          onEdit={onEdit}
          onSave={onSave}
          onDiscard={onDiscard}
        />
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
