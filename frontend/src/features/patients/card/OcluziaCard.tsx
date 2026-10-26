import { useState, type FormEvent } from 'react'
import { Icon } from '../../../components/Icon'
import type { CardActions } from './actions'
import { patientCard, type Ocluzie, type PatientCard } from './card'

/* Прикус — графа «Ocluzia» формы 043/e (26.10, волна 3 одонтограммы; слово
   Олега 25.10: «пока без ортодонта»). Одна запись на пациента, как анамнез:
   свёрнутая секция показывает САМУ запись (та же строка, что на листе),
   форма — по клику. ⛔ Никаких норм: пусто = «не записано», а не «нет» и не
   «норма» — поэтому перекрёстный и открытый прикус словами, а не галочкой.
   Классы Энгля и сторона — списки сервера (`options.ocluzie`), мм — как
   пишут («3», «2,5», «-1»), проверяет сервер и подсвечивает поле.
   ⭐ Черновик живёт у ЭКРАНА фиши (`OcDraft`, как `AnDraft` 01.10): вкладка
   «Date pacient» размонтируется при переходе, и набранное пропадало бы. */
const T = {
  title: 'Ocluzia',
  none: 'neînregistrată',
  empty: 'înregistrare goală',
  filled: 'Înregistrat:',
  notFilled: 'Nu a fost înregistrată — se completează la examenul obiectiv',
  form: 'Examen ocluzal',
  unsaved: 'modificări nesalvate',
  save: 'Salvează ocluzia',
  angle: 'Clasa Angle',
  dr: 'dreapta',
  st: 'stânga',
  overjet: 'Overjet (mm)',
  overbite: 'Overbite (mm)',
  incrucisata: 'Ocluzie încrucișată (dinți / parte)',
  incrucisataPh: 'ex. 13–43 sau dreapta',
  deschisa: 'Ocluzie deschisă (zona)',
  deschisaPh: 'ex. frontal 12–22',
  mediana: 'Linia mediană, deviere',
  medianaMm: 'mm',
  medianaSpre: 'spre',
  nota: 'Notă',
  notaPh: 'ex. abraziune, interferențe',
  doctor: 'Medic',
  doctorNone: '— fără medic —',
} as const

/** Черновик формы, привязанный к записи, с которой начат: свежая фиша
 *  (другой объект `oc`) даёт форме свои значения. */
export interface OcDraft {
  oc: Ocluzie
  fields: Record<string, string>
}

/** Есть ли в черновике то, чего нет в сохранённой записи этой фиши. */
export function ocDirty(draft: OcDraft | null, oc: Ocluzie): boolean {
  if (!draft || draft.oc !== oc) return false
  const keys = new Set([...Object.keys(draft.fields), ...Object.keys(oc.fields)])
  return [...keys].some((k) => (draft.fields[k] ?? '').trim() !== (oc.fields[k] ?? '').trim())
}

interface Props {
  card: PatientCard
  a: CardActions
  draft: OcDraft | null
  onDraft: (d: OcDraft) => void
}

const MM = /^-?\d{1,2}([.,]\d{1,2})?$/
/* поля в миллиметрах — только у них «не число» подсвечивается до отправки */
const MM_FIELDS = new Set(['overjet', 'overbite', 'mediana_mm'])

export function OcluziaCard({ card, a, draft, onDraft }: Props) {
  const oc = card.ocluzie
  const opts = card.options.ocluzie
  const cur: OcDraft = draft && draft.oc === oc ? draft : { oc, fields: oc.fields }
  const f = cur.fields
  const set = (k: string, v: string) => onDraft({ ...cur, fields: { ...f, [k]: v } })
  const dirty = ocDirty(draft, oc)
  /* раскрыта, пока прикус не записан (как опросник анамнеза) */
  const [open, setOpen] = useState(!oc.filled)
  /* поле, которое сервер назвал в отказе (`error.field`) — подсветка */
  const [bad, setBad] = useState('')

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const err = await a.act(() => patientCard.saveOcluzie(a.pid, a.views, f))
    setBad(err?.field ?? '')
  }

  const head = !oc.filled
    ? <span className="pill grey">{T.none}</span>
    : !oc.summary ? <span className="pill grey">{T.empty}</span> : null
  const mmBad = (k: string) => MM_FIELDS.has(k) && (f[k] ?? '').trim() !== '' && !MM.test((f[k] ?? '').trim())
  const cls = (k: string, extra = '') =>
    [extra, bad === k || mmBad(k) ? 'is-bad' : ''].filter(Boolean).join(' ') || undefined

  return (
    <div className="fcard" id="ocluzia">
      <h3>{T.title} {head}{dirty && <span className="pill orange dp-unsaved">{T.unsaved}</span>}</h3>
      {oc.summary && <p className="ocsum">{oc.summary}</p>}
      <small className="hint dp-m0">
        {oc.filled ? `${T.filled} ${oc.when} · ${oc.author || '—'}` : T.notFilled}
      </small>
      <details className="anform" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary><Icon name="pen" /> {T.form}</summary>
        <form className="fform ocform" onSubmit={onSubmit}>
          <fieldset className="ocrow">
            <legend>{T.angle}</legend>
            {(['angle_dr', 'angle_st'] as const).map((k) => (
              <label key={k} className={cls(k, 'dlab')}>{k === 'angle_dr' ? T.dr : T.st}
                <select value={f[k] ?? ''} onChange={(e) => set(k, e.target.value)}>
                  {opts.angle.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
                </select>
              </label>
            ))}
          </fieldset>
          <div className="ocrow">
            <label className={cls('overjet', 'dlab')}>{T.overjet}
              <input inputMode="decimal" maxLength={6} value={f.overjet ?? ''}
                     onChange={(e) => set('overjet', e.target.value)} />
            </label>
            <label className={cls('overbite', 'dlab')}>{T.overbite}
              <input inputMode="decimal" maxLength={6} value={f.overbite ?? ''}
                     onChange={(e) => set('overbite', e.target.value)} />
            </label>
          </div>
          <label className={cls('incrucisata', 'dlab')}>{T.incrucisata}
            <input maxLength={100} placeholder={T.incrucisataPh} value={f.incrucisata ?? ''}
                   onChange={(e) => set('incrucisata', e.target.value)} />
          </label>
          <label className={cls('deschisa', 'dlab')}>{T.deschisa}
            <input maxLength={100} placeholder={T.deschisaPh} value={f.deschisa ?? ''}
                   onChange={(e) => set('deschisa', e.target.value)} />
          </label>
          <fieldset className="ocrow">
            <legend>{T.mediana}</legend>
            <label className={cls('mediana_mm', 'dlab')}>{T.medianaMm}
              <input inputMode="decimal" maxLength={6} value={f.mediana_mm ?? ''}
                     onChange={(e) => set('mediana_mm', e.target.value)} />
            </label>
            <label className={cls('mediana_spre', 'dlab')}>{T.medianaSpre}
              <select value={f.mediana_spre ?? ''} onChange={(e) => set('mediana_spre', e.target.value)}>
                {opts.sides.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
            </label>
          </fieldset>
          <label className={cls('doctor', 'dlab')}>{T.doctor}
            <select value={f.doctor ?? ''} onChange={(e) => set('doctor', e.target.value)}>
              <option value="">{T.doctorNone}</option>
              {card.options.doctors.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
          <label className={cls('nota', 'dlab')}>{T.nota}
            <textarea rows={2} maxLength={500} placeholder={T.notaPh} value={f.nota ?? ''}
                      onChange={(e) => set('nota', e.target.value)} />
          </label>
          <button disabled={a.busy}><Icon name="save" /> {T.save}</button>
        </form>
      </details>
    </div>
  )
}
