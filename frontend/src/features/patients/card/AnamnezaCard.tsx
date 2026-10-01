import { useEffect, useRef, useState, type FormEvent } from 'react'
import { AppLink } from '../../../components/AppLink'
import { Icon } from '../../../components/Icon'
import type { CardActions } from './actions'
import { patientCard, type Anamneza, type PatientCard } from './card'
import { printHref } from './print'

/* Опросник анамнеза: свёрнутая секция обязана показывать САМО содержимое —
   врач смотрит на неё перед анестезией и раскрывать «Chestionar» не будет.
   Риски (галочки И свободный текст) посчитаны на сервере.
   ⭐ Черновик живёт у ЭКРАНА фиши, не у карточки (01.10): вкладки
   размонтированы, и две галочки, поставленные до «Salvează», пропадали при
   щелчке по соседней вкладке — молча, без вопроса. */
const T = {
  title: 'Anamneză',
  risk: 'de reținut',
  noRisk: 'fără riscuri',
  none: 'necompletată',
  filled: 'Completat:',
  notFilled: 'Nu a fost completată — întrebați pacientul înainte de tratament',
  print: 'Formular pentru pacient',
  form: 'Chestionar',
  unsaved: 'modificări nesalvate',
  save: 'Salvează anamneza',
} as const

/** Черновик опросника, привязанный к анамнезу, с которого начат: свежая
 *  фиша (другой объект `an`) даёт форме свои значения. */
export interface AnDraft {
  an: Anamneza
  flags: string[]
  texts: Record<string, string>
}

const same = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x))

/** Есть ли в черновике то, чего нет в сохранённом анамнезе этой фиши. */
export function anDirty(draft: AnDraft | null, an: Anamneza): boolean {
  if (!draft || draft.an !== an) return false
  if (!same(draft.flags, an.flags)) return true
  const keys = new Set([...Object.keys(draft.texts), ...Object.keys(an.texts)])
  return [...keys].some((k) => (draft.texts[k] ?? '').trim() !== (an.texts[k] ?? '').trim())
}

interface Props {
  card: PatientCard
  a: CardActions
  draft: AnDraft | null
  onDraft: (d: AnDraft) => void
  /** Просьба показать опросник (кнопка «Anamneză» в шапке): раскрыть и подвести. */
  focusTick: number
}

export function AnamnezaCard({ card, a, draft, onDraft, focusTick }: Props) {
  const an = card.anamneza
  const opts = card.options
  const cur: AnDraft = draft && draft.an === an ? draft : { an, flags: an.flags, texts: an.texts }
  const { flags, texts } = cur
  const edit = (patch: Partial<AnDraft>) => onDraft({ ...cur, ...patch })
  const dirty = anDirty(draft, an)
  const [open, setOpen] = useState(!an.filled)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!focusTick) return
    setOpen(true)
    const el = box.current
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'start' })
  }, [focusTick])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    await a.act(() => patientCard.saveAnamneza(a.pid, a.views, flags, texts))
  }

  const head = an.state === 'none'
    ? <span className="pill red">{T.none}</span>
    : an.state === 'risk'
      ? <span className="pill orange">{an.n_risk} {T.risk}</span>
      : <span className="pill green">{T.noRisk}</span>
  const chips = [
    ...an.marked.map((m) => ({ icon: 'sos' as const, text: m })),
    ...an.free.map((f) => ({ icon: 'note' as const, text: `${f.label}: ${f.text.slice(0, 70)}` })),
  ]

  return (
    <div className="fcard" id="anamneza" ref={box}>
      <h3>{T.title} {head}{dirty && <span className="pill orange dp-unsaved">{T.unsaved}</span>}</h3>
      {chips.length > 0 && (
        <div className="anlist">
          {chips.map((c, i) => <span key={i}><Icon name={c.icon} /> {c.text}</span>)}
        </div>
      )}
      <small className="hint dp-m0">
        {an.filled ? `${T.filled} ${an.when} · ${an.author || '—'}` : T.notFilled}
      </small>
      {/* ⛔ Без target="_blank" — как 043/e и acord. Окно программы (pywebview,
          OPEN_EXTERNAL_LINKS_IN_BROWSER) отдаёт «новое окно» СИСТЕМНОМУ
          браузеру: там нет куки входа, бланк просит PIN, а ссылка «назад» с
          него уводит весь журнал в браузер. Бланк печатается кнопкой и
          возвращает ссылкой — новая вкладка ему не нужна. */}
      <AppLink className="anprint" href={printHref(card.id, 'anamneza/print', a.back)}>
        <Icon name="print" /> {T.print}
      </AppLink>
      <details className="anform" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary><Icon name="pen" /> {T.form}</summary>
        <form className="fform" onSubmit={onSubmit}>
          <div className="anbox">
            {opts.anamneza_flags.map((f) => (
              <label key={f.id}>
                <input type="checkbox" checked={flags.includes(f.id)}
                       onChange={(e) => edit({ flags: e.target.checked ? [...flags, f.id] : flags.filter((x) => x !== f.id) })} />
                {' '}{f.label}
              </label>
            ))}
          </div>
          {opts.anamneza_texts.map((t) => (
            <label key={t.id} className="dlab">{t.label}
              <textarea rows={2} maxLength={500} placeholder={t.placeholder} value={texts[t.id] ?? ''}
                        onChange={(e) => edit({ texts: { ...texts, [t.id]: e.target.value } })} />
            </label>
          ))}
          <button disabled={a.busy}><Icon name="save" /> {T.save}</button>
        </form>
      </details>
    </div>
  )
}
