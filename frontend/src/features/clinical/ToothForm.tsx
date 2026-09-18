import type { FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { surfaceLetter, surfaceName, type Odontogram, type ToothInfo } from './chart'
import type { ToothDraft } from './useChart'

/* Форма зуба — ОДНА на инспектор детальной страницы и диалог компактной
   карточки: поверхности с состоянием на каждую, состояние зуба, отметки,
   врач, заметка. Форма КОНТРОЛИРУЕМАЯ (C22): черновик живёт в useChart —
   его правят ещё клик по рисунку и контекстное меню, а форма его только
   показывает и меняет через onEdit. Намерение уезжает явно (карта
   поверхностей и список отметок всегда, state0 — как показали). Разметка
   та же, что у старой страницы (.sfbtns, .sfstate, .mkrow, .dlg-form). */
const T = {
  surfaces: 'Suprafețe',
  surfaceState: 'Starea suprafeței',
  none: '— fără leziune',
  state: 'Starea dintelui',
  doctorNone: 'Medic —',
  note: 'Notiță (opțional)',
  save: 'Salvează',
  discard: 'Renunță',
  unsaved: 'Nesalvat',
} as const

interface Props {
  model: Odontogram
  n: number
  info: ToothInfo
  busy: boolean
  /** Выбранная поверхность — состояние родителя (её выбирают и с рисунка). */
  sel: string
  onSel: (letter: string) => void
  draft: ToothDraft
  dirty: boolean
  onEdit: (patch: Partial<ToothDraft>) => void
  onSave: () => void
  onDiscard: () => void
}

export function ToothForm({ model, n, info, busy, sel, onSel, draft: d, dirty, onEdit: edit, onSave, onDiscard }: Props) {
  const order = Object.keys(model.surfaces)

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    onSave()
  }

  const selState = d.sfst[sel] ?? ''
  return (
    <form className="dlg-form insp-f" onSubmit={onSubmit}>
      <div className="insp-t">{T.surfaces}</div>
      <div className="sfbtns">
        {order.map((k) => {
          const st = d.sfst[k] ?? ''
          return (
            <button
              key={k}
              type="button"
              className={`sfbtn${st ? ` on sf-${st}` : ''}${k === sel ? ' sel' : ''}`}
              aria-pressed={st ? 'true' : 'false'}
              data-s={k}
              title={surfaceName(k, info.jaw, model.surfaces)}
              onClick={() => onSel(k)}
            >
              {surfaceLetter(k, info.jaw)} <small>{surfaceName(k, info.jaw, model.surfaces)}</small>
            </button>
          )
        })}
      </div>
      <div className="sfstate">
        <label htmlFor={`sfstate-${n}`}>{T.surfaceState} <b>{surfaceLetter(sel, info.jaw)}</b></label>
        <select
          id={`sfstate-${n}`}
          value={selState}
          onChange={(e) => {
            const next = { ...d.sfst }
            if (e.target.value) next[sel] = e.target.value
            else delete next[sel]
            edit({ sfst: next })
          }}
        >
          <option value="">{T.none}</option>
          {model.surface_states.map((s) => <option key={s} value={s}>{model.states[s] ?? s}</option>)}
        </select>
      </div>
      <div className="insp-t">{T.state}</div>
      <select aria-label={T.state} value={d.state} onChange={(e) => edit({ state: e.target.value })}>
        {Object.entries(model.states).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <div className="mkrow">
        {Object.entries(model.marks).map(([k, v]) => (
          <label key={k} className="mkbox">
            <input
              type="checkbox"
              checked={d.marks.includes(k)}
              onChange={(e) => edit({ marks: e.target.checked ? [...d.marks, k] : d.marks.filter((x) => x !== k) })}
            />
            {v}
          </label>
        ))}
      </div>
      <select aria-label={T.doctorNone} value={d.doctor} onChange={(e) => edit({ doctor: e.target.value })}>
        <option value="">{T.doctorNone}</option>
        {model.doctors.map((doc) => <option key={doc} value={doc}>{doc}</option>)}
      </select>
      <input
        value={d.note}
        onChange={(e) => edit({ note: e.target.value })}
        placeholder={T.note}
        aria-label={T.note}
        maxLength={120}
      />
      <div className="dp-save-row">
        <button disabled={busy}><Icon name="save" /> {T.save}</button>
        {dirty && (
          <>
            <button type="button" className="pl-btn" onClick={onDiscard}>{T.discard}</button>
            <span className="dp-draft">{T.unsaved}</span>
          </>
        )}
      </div>
    </form>
  )
}
