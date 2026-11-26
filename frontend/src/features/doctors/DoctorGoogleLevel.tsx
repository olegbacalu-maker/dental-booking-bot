import { useEffect, useId, useRef, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { showDialog, useDialogLeave } from '../../components/dialog'
import { Icon } from '../../components/Icon'
import type { GdocList, GdocListWords, GdocLevelCode, GdocRow, LevelChoice } from './gdoc'

/* Полоса «Calendarele medicilor în Google» вверху списка Medici: что видит врач в событиях своего
   календаря — три положения, под ними образец события. Видят директор и регистратура, менять —
   только `level.can_set` (директор с ПК программы); почему нельзя — словом сервера `lock`. Уровень
   с данными пациента (`warn`) ставится только через окно с галочкой. Все слова — сервера.
   Выбор подписан видимо и залит фирменным цветом: серый на сером его не замечали; срок переписи —
   под самим выбором, к нему он и относится. */

interface Props {
  g: GdocList
  busy: boolean
  /** Выбранный уровень и согласие; `true` — сервер принял, ответ принёс новый `level`. */
  onSet: (code: GdocLevelCode, ack: boolean) => Promise<boolean>
}

export function DoctorGoogleLevel({ g, busy, onSet }: Props) {
  const w = g.words
  const lv = g.level
  const cur = lv.choices.find((c) => c.code === lv.code)
  const [asking, setAsking] = useState<LevelChoice | null>(null)
  const labId = useId()

  if (g.premium) {
    return (
      <section className="dp-card gdl gdl-prem" data-gdl="premium" aria-label={w.title}>
        <span className="gl-mark plus"><Icon name="lock" /></span>
        <p className="gdl-line">
          <b>{w.premium}</b> {w.premium_more}{' '}
          <AppLink className="gl-lic" href={g.premium.href}>{g.premium.label} ›</AppLink>
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
    <section className="dp-card gdl" data-gdl={lv.code} aria-label={w.title}>
      <div className="gdl-top">
        <span className="gl-mark"><Icon name="cal" /></span>
        <div className="gdl-ttl">
          <b>{w.title}</b>
          <span>{w.count ? `${w.count} · ` : ''}{w.lead}</span>
        </div>
        <div className="gdl-pick">
          <div className="gdl-pickr">
            <span className="gdl-lab" id={labId}>{w.label}:</span>
            <div className="gdl-seg" role="radiogroup" aria-labelledby={labId}>
              {lv.choices.map((c) => (
                <button key={c.code} type="button" role="radio" aria-checked={c.code === lv.code}
                        className={`gdl-sb${c.code === lv.code ? ' on' : ''}`}
                        disabled={busy || (!lv.can_set && c.code !== lv.code)} onClick={() => pick(c)}>
                  {c.label}{c.code === 'time' ? <small>{w.default}</small> : null}
                </button>
              ))}
            </div>
          </div>
          <span className="gdl-note">
            {lv.lock ? <span className="gdl-lock"><Icon name="lock" /> {lv.lock}</span> : <span className="hint">{w.rewrite}</span>}
          </span>
        </div>
      </div>
      {cur ? (
        <p className="gdl-sub">
          <span className="gdl-ph"><Icon name="phone" /> {w.phone} <span className="gdl-ev">{cur.sample}</span></span>
        </p>
      ) : null}
      {asking ? (
        <LevelAsk c={asking} w={w} busy={busy} onClose={() => setAsking(null)}
                  onOk={() => onSet(asking.code, true)} />
      ) : null}
    </section>
  )
}

/** Окно уровня с данными пациента: «Alege» заперта, пока не стоит «Am înțeles». */
function LevelAsk({ c, w, busy, onClose, onOk }: {
  c: LevelChoice; w: GdocListWords; busy: boolean; onClose: () => void; onOk: () => Promise<boolean>
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const { leave } = useDialogLeave(ref, onClose)
  const [ack, setAck] = useState(false)
  useEffect(() => { showDialog(ref.current) }, [])
  async function save() {
    if (await onOk()) leave()
  }
  return (
    <dialog ref={ref} className="rg-dlg gdl-dlg" onClose={leave} aria-label={w.dlg_title}>
      <div className="dlg-head">
        <span><Icon name="cal" /> {w.dlg_title}</span>
        <button type="button" className="rg-x" onClick={leave} aria-label={w.dlg_cancel}><Icon name="close" /></button>
      </div>
      <div className="rg-dlg-b">
        <p className="gdl-pickd"><b>{c.label}</b> — {w.phone} <span className="gdl-ev">{c.sample}</span></p>
        <div className="gdl-warn">
          <p><Icon name="excl" /> <span>{c.warn}</span></p>
          <label className="gl-chk">
            <input type="checkbox" checked={ack} disabled={busy} onChange={(e) => setAck(e.target.checked)} />
            <span>{w.dlg_ack}</span>
          </label>
        </div>
      </div>
      <div className="rg-dlg-f">
        <button type="button" className="dp-btn pri" disabled={busy || !ack} onClick={() => { void save() }}>
          <Icon name="check" /> {w.dlg_ok} „{c.label}”
        </button>
        <button type="button" className="rc-btn" disabled={busy} onClick={leave}>{w.dlg_cancel}</button>
      </div>
    </dialog>
  )
}

/** Плашка врача в списке: строкой рядом с часами; нет слова сервера для состояния — плашки нет. */
export function DoctorGoogleChip({ row, words }: { row: GdocRow | undefined; words: GdocListWords }) {
  const text = row ? words.chip[row.state] : undefined
  if (!row || !text) return null
  const tone = row.state === 'on' ? 'ok'
    : row.state === 'off' || row.state === 'readonly' || row.state === 'paused' || row.state === 'premium' ? 'mute' : 'warn'
  return <span className={`gd-chip ${tone}`} data-gd={row.state}><Icon name={tone === 'warn' ? 'excl' : 'cal'} /> {text}</span>
}
