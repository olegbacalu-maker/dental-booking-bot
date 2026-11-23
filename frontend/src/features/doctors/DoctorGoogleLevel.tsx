import { useEffect, useRef, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { showDialog, useDialogLeave } from '../../components/dialog'
import { Icon } from '../../components/Icon'
import type { GdocList, GdocLevelCode, GdocRow, GdocWords, LevelChoice } from './gdoc'

/* Полоса «Calendarele medicilor în Google» вверху списка Medici: что видит врач в событиях своего
   календаря — три положения, под ними образец события. Видят директор и регистратура, менять —
   только `level.can_set` (директор с ПК программы). Уровень с данными пациента (`warn`) ставится
   только через окно с галочкой. Все слова — сервера. */

interface Props {
  g: GdocList
  busy: boolean
  /** Выбранный уровень и согласие; ответ сервера приносит новый `level`. */
  onSet: (code: GdocLevelCode, ack: boolean) => Promise<boolean>
}

export function DoctorGoogleLevel({ g, busy, onSet }: Props) {
  const w = g.words
  const lv = g.level
  const cur = lv.choices.find((c) => c.code === lv.code)
  const [asking, setAsking] = useState<LevelChoice | null>(null)
  const premium = premiumLine(g)

  if (premium) {
    return (
      <section className="dp-card gdl gdl-prem" data-gdl="premium" aria-label={w.list_title}>
        <span className="gl-mark plus"><Icon name="lock" /></span>
        <p className="gdl-line">
          <b>{premium.text}</b>
          {g.premium ? <> {w.premium_lead} <AppLink className="gl-lic" href={g.premium.href}>{g.premium.label} ›</AppLink></> : null}
        </p>
      </section>
    )
  }

  const pick = (c: LevelChoice) => {
    if (!lv.can_set || busy || c.code === lv.code) return
    if (c.warn) setAsking(c)
    else void onSet(c.code, false)
  }
  return (
    <section className="dp-card gdl" data-gdl={lv.code} aria-label={w.list_title}>
      <div className="gdl-top">
        <span className="gl-mark"><Icon name="cal" /></span>
        <div className="gdl-ttl">
          <b>{w.list_title}</b>
          <span>{w.count ? `${w.count} · ` : ''}{w.level_title}</span>
        </div>
        <div className="gdl-seg" role="radiogroup" aria-label={w.level_title}>
          {lv.choices.map((c) => (
            <button key={c.code} type="button" role="radio" aria-checked={c.code === lv.code}
                    className={`gdl-sb${c.code === lv.code ? ' on' : ''}`}
                    disabled={busy || (!lv.can_set && c.code !== lv.code)} onClick={() => pick(c)}>
              <span className="gdl-cap">{c.label}</span>
              {c.code === 'time' && w.level_default ? <small>{w.level_default}</small> : null}
            </button>
          ))}
        </div>
      </div>
      <p className="gdl-sub">
        {cur ? (
          <span className="gdl-ph">
            <Icon name="phone" /> {w.level_label}{' '}
            {cur.sample ? <span className="gdl-ev">{cur.sample}</span> : <span>{cur.hint}</span>}
          </span>
        ) : null}
        <span className="gdl-note">
          {!lv.can_set && lv.lock ? <span className="gdl-lock"><Icon name="lock" /> {lv.lock}</span>
            : w.rewrite ? <span className="hint">{w.rewrite}</span> : null}
        </span>
      </p>
      {asking ? (
        <LevelAsk c={asking} w={w} busy={busy} onClose={() => setAsking(null)}
                  onOk={() => onSet(asking.code, true)} />
      ) : null}
    </section>
  )
}

/** Без права у клиники все врачи в `premium`/`paused`: одна строка вместо выбора. */
function premiumLine(g: GdocList): { text: string } | null {
  const rows = Object.values(g.doctors)
  if (!g.premium && !(rows.length && rows.every((r) => r.state === 'premium' || r.state === 'paused'))) return null
  const why = rows.find((r) => r.why?.text)?.why
  return { text: why?.text ? (/[.!?…]$/.test(why.text) ? why.text : `${why.text}.`) : g.words.list_title }
}

/** Окно уровня с данными пациента: «Salvează» заперта, пока не стоит «Am înțeles». */
function LevelAsk({ c, w, busy, onClose, onOk }: {
  c: LevelChoice; w: GdocWords; busy: boolean; onClose: () => void; onOk: () => Promise<boolean>
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const { leave } = useDialogLeave(ref, onClose)
  const [ack, setAck] = useState(false)
  useEffect(() => { showDialog(ref.current) }, [])
  async function save() {
    if (await onOk()) leave()
  }
  return (
    <dialog ref={ref} className="rg-dlg gdl-dlg" onClose={leave} aria-label={w.level_title}>
      <div className="dlg-head">
        <span><Icon name="cal" /> {w.level_title}</span>
        <button type="button" className="rg-x" onClick={leave} aria-label={w.cancel}><Icon name="close" /></button>
      </div>
      <div className="rg-dlg-b">
        <p className="gdl-pickd">
          <b className="gdl-cap">{c.label}</b> — {w.level_label}{' '}
          {c.sample ? <span className="gdl-ev">{c.sample}</span> : c.hint}
        </p>
        <div className="gdl-warn">
          <p><Icon name="excl" /> <span>{c.warn}</span></p>
          <label className="gl-chk">
            <input type="checkbox" checked={ack} disabled={busy} onChange={(e) => setAck(e.target.checked)} />
            <span>{w.level_ack}</span>
          </label>
        </div>
      </div>
      <div className="rg-dlg-f">
        <button type="button" className="dp-btn pri" disabled={busy || !ack} onClick={() => { void save() }}>
          <Icon name="check" /> {w.level_save}
        </button>
        <button type="button" className="rc-btn" disabled={busy} onClick={leave}>{w.cancel}</button>
      </div>
    </dialog>
  )
}

/** Плашка врача в списке: строкой рядом с часами; нет слова сервера для состояния — плашки нет. */
export function DoctorGoogleChip({ row, words }: { row: GdocRow | undefined; words: GdocWords }) {
  const text = row ? words.chip?.[row.state] : undefined
  if (!row || !text) return null
  const tone = row.state === 'on' ? 'ok'
    : row.state === 'off' || row.state === 'readonly' || row.state === 'paused' || row.state === 'premium' ? 'mute' : 'warn'
  return <span className={`gd-chip ${tone}`} data-gd={row.state}><Icon name={tone === 'warn' ? 'excl' : 'cal'} /> {text}</span>
}
