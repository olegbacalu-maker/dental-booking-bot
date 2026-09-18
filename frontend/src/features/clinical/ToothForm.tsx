import { useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { surfaceLetter, surfaceName, type Odontogram, type ToothInfo, type ToothSave } from './chart'

/* Форма зуба — ОДНА на инспектор детальной страницы и диалог компактной
   карточки: поверхности с состоянием на каждую, состояние зуба, отметки,
   врач, заметка. Намерение уезжает явно (карта поверхностей и список
   отметок всегда, state0 — как показали), см. ToothSave. Разметка та же,
   что у старой страницы (.sfbtns, .sfstate, .mkrow, .dlg-form).
   ⚠️ Родитель монтирует форму с `key` по зубу и счётчику сохранений: так
   смена зуба и свежая модель после удачи дают форме новые значения без
   эффекта, а отказ сервера ввод не трогает. */
const T = {
  surfaces: 'Suprafețe',
  surfaceState: 'Starea suprafeței',
  none: '— fără leziune',
  state: 'Starea dintelui',
  doctorNone: 'Medic —',
  note: 'Notiță (opțional)',
  save: 'Salvează',
} as const

interface Draft {
  state: string
  sfst: Record<string, string>
  marks: string[]
  doctor: string
  note: string
}

/** Поверхность, выбранная по умолчанию: первая отмеченная, иначе жевательная —
 *  поверхность выбирается СРАЗУ, иначе список её состояния скрыт до первого
 *  клика по букве, а догадаться, что по букве надо кликать, неоткуда. */
export function defaultSurface(info: ToothInfo, order: string[]): string {
  return order.find((k) => info.sfst[k]) ?? 'O'
}

interface Props {
  model: Odontogram
  n: number
  info: ToothInfo
  busy: boolean
  /** Выбранная поверхность — состояние родителя (её выбирают и с рисунка). */
  sel: string
  onSel: (letter: string) => void
  onSave: (n: number, body: ToothSave) => void
}

export function ToothForm({ model, n, info, busy, sel, onSel, onSave }: Props) {
  const order = Object.keys(model.surfaces)
  const [d, setD] = useState<Draft>(() => ({
    state: info.state, sfst: { ...info.sfst }, marks: [...info.mk], doctor: info.doctor, note: info.note,
  }))
  const edit = (patch: Partial<Draft>) => setD((cur) => ({ ...cur, ...patch }))

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    onSave(n, { state: d.state, state0: info.state, note: d.note, doctor: d.doctor, surfaces: d.sfst, marks: d.marks })
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
      <button disabled={busy}><Icon name="save" /> {T.save}</button>
    </form>
  )
}
