import { useState, type FormEvent } from 'react'
import { AppLink } from '../../../components/AppLink'
import { Icon } from '../../../components/Icon'
import type { CardActions } from './actions'
import { patientCard, type Anamneza, type PatientCard } from './card'

/* Опросник анамнеза: свёрнутая секция обязана показывать САМО содержимое —
   врач смотрит на неё перед анестезией и раскрывать «Chestionar» не будет.
   Риски (галочки И свободный текст) посчитаны на сервере. */
const T = {
  title: 'Anamneză',
  risk: 'de reținut',
  noRisk: 'fără riscuri',
  none: 'necompletată',
  filled: 'Completat:',
  notFilled: 'Nu a fost completată — întrebați pacientul înainte de tratament',
  print: 'Formular pentru pacient',
  form: 'Chestionar',
  save: 'Salvează anamneza',
} as const

interface Props {
  card: PatientCard
  a: CardActions
}

interface Draft {
  an: Anamneza
  flags: string[]
  texts: Record<string, string>
}

export function AnamnezaCard({ card, a }: Props) {
  const an = card.anamneza
  const opts = card.options
  /* черновик привязан к анамнезу, с которого начат: свежая фиша даёт форме
     свои значения, отказ сервера ввод не трогает (выводится при отрисовке) */
  const [draft, setDraft] = useState<Draft>(() => ({ an, flags: an.flags, texts: an.texts }))
  const cur = draft.an === an ? draft : { an, flags: an.flags, texts: an.texts }
  const { flags, texts } = cur
  const edit = (patch: Partial<Draft>) =>
    setDraft((d) => ({ ...(d.an === an ? d : { an, flags: an.flags, texts: an.texts }), ...patch }))

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
    <div className="fcard" id="anamneza">
      <h3>{T.title} {head}</h3>
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
      <AppLink className="anprint" href={`/admin/patient/${card.id}/anamneza/print`}>
        <Icon name="print" /> {T.print}
      </AppLink>
      <details className="anform" open={!an.filled}>
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
