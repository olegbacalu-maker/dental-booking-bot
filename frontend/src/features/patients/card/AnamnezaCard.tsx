import { useState, type FormEvent } from 'react'
import { AppLink } from '../../../components/AppLink'
import { Icon } from '../../../components/Icon'
import type { CardActions } from './actions'
import { patientCard, type Anamneza, type PatientCard } from './card'
import { printHref } from './print'

/* Опросник анамнеза: свёрнутая секция обязана показывать САМО содержимое —
   врач смотрит на неё перед анестезией и раскрывать «Chestionar» не будет.
   Риски (галочки И свободный текст) посчитаны на сервере.
   «Niciuna dintre afecțiunile de mai sus» (Олег 23.10) — последняя строка
   списка, ключ `options.anamneza_none` в той же строке flags: отметил её —
   двенадцать снимаются, отметил любую из двенадцати — она снимается (сервер
   на оба разом отвечает отказом). Свободные поля она не трогает. Сохранённая
   — серый чип словами медзаписи, дата — строкой «Completat».
   ⭐ Черновик живёт у ЭКРАНА фиши, не у карточки (01.10): вкладки
   размонтированы, и две галочки, поставленные до «Salvează», пропадали при
   щелчке по соседней вкладке — молча, без вопроса. */
const T = {
  title: 'Anamneză',
  risk: 'de reținut',
  noRisk: 'fără riscuri',
  none: 'necompletată',
  denies: 'Neagă afecțiunile din chestionar',
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
  /** Просьба показать опросник (кнопка «Anamneză» в шапке): раскрыть. */
  focusTick: number
}

export function AnamnezaCard({ card, a, draft, onDraft, focusTick }: Props) {
  const an = card.anamneza
  const opts = card.options
  const cur: AnDraft = draft && draft.an === an ? draft : { an, flags: an.flags, texts: an.texts }
  const { flags, texts } = cur
  const edit = (patch: Partial<AnDraft>) => onDraft({ ...cur, ...patch })
  const dirty = anDirty(draft, an)
  /* раскрыт, пока опросник не собран — или когда его попросили из шапки
     (карточка монтируется уже с просьбой: вкладка была другой) */
  const [open, setOpen] = useState(!an.filled || focusTick > 0)
  /* повторная просьба раскрывает опросник ПРИ ОТРИСОВКЕ (правило хуков:
     состояние из пропа — без эффекта).
     ⛔ Экран НЕ подводится (14.10, слово Олега: «просто переключиться на
     вкладку»): `scrollIntoView` ставил заголовок опросника ПОД липкую шапку
     программы, а вкладки и шапка фиши уезжали за край — вкладка и так
     открывается с опросником сверху справа. */
  const [seenTick, setSeenTick] = useState(focusTick)
  if (focusTick !== seenTick) {
    setSeenTick(focusTick)
    setOpen(true)
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    await a.act(() => patientCard.saveAnamneza(a.pid, a.views, flags, texts))
  }

  const head = an.state === 'none'
    ? <span className="pill red">{T.none}</span>
    : an.state === 'risk'
      ? <span className="pill orange">{an.n_risk} {T.risk}</span>
      : <span className="pill green">{T.noRisk}</span>
  const none = opts.anamneza_none
  const chips = [
    ...(an.denies ? [{ icon: 'check' as const, text: T.denies, cls: 'none' }] : []),
    ...an.marked.map((m) => ({ icon: 'sos' as const, text: m, cls: '' })),
    ...an.free.map((f) => ({ icon: 'note' as const, text: `${f.label}: ${f.text.slice(0, 70)}`, cls: '' })),
  ]

  return (
    <div className="fcard" id="anamneza">
      <h3>{T.title} {head}{dirty && <span className="pill orange dp-unsaved">{T.unsaved}</span>}</h3>
      {chips.length > 0 && (
        <div className="anlist">
          {chips.map((c, i) => <span key={i} className={c.cls || undefined}><Icon name={c.icon} /> {c.text}</span>)}
        </div>
      )}
      <small className="hint dp-m0">
        {an.filled ? `${T.filled} ${an.when} · ${an.author || '—'}` : T.notFilled}
      </small>
      {/* ⛔ Без target="_blank" — как 043/e и acord. Окно программы (оболочка
          Tauri) отдаёт «новое окно» СИСТЕМНОМУ браузеру: там нет куки входа,
          бланк просит PIN, а ссылка «назад» с него уводит весь журнал в
          браузер. Бланк печатается кнопкой и
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
                       onChange={(e) => edit({ flags: e.target.checked
                         ? [...flags.filter((x) => x !== none.id), f.id]
                         : flags.filter((x) => x !== f.id) })} />
                {' '}{f.label}
              </label>
            ))}
            {/* ответ на весь список — последней строкой, на всю ширину */}
            <label className="annone">
              <input type="checkbox" checked={flags.includes(none.id)}
                     onChange={(e) => edit({ flags: e.target.checked ? [none.id] : flags.filter((x) => x !== none.id) })} />
              {' '}{none.label}
            </label>
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
