import type { ReactNode } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import type { IconName } from '../../components/icons'
import type { GdocView } from './gdoc'

/* Блок «Calendarul medicului în Google» карточкой в левой колонке карточки врача. Состояние,
   кнопки (`can`) и все слова — сервера (`gcal_doctor.view`). У подключённого врача место под
   строки состояния занято всегда: опрос, переводящий «actualizat» в «nu a reușit» и обратно, не
   меняет высоту карточки и не двигает контакты под ней. */

interface Props {
  g: GdocView
  busy: boolean
  /** Идёт «Sincronizează acum»: вращается значок, подпись та же — кнопка не меняет ширину. */
  checking: boolean
  onConnect: () => void
  onCancel: () => void
  onCheck: () => void
  onDisconnect: () => void
}

const TONE: Record<string, string> = { ok: 'ok', warn: 'warn', err: 'err' }
/** Связь стоит, но не идёт: без права или в режиме чтения — серый замок, а не тревога. */
const STOPPED = new Set(['premium', 'paused', 'readonly'])

export function DoctorGoogle({ g, busy, checking, onConnect, onCancel, onCheck, onDisconnect }: Props) {
  const w = g.words
  const can = g.can
  const box = (body: ReactNode, cls = '') => (
    <section className={`fcard gd${cls ? ` ${cls}` : ''}`} data-gd={g.state} aria-label={w.title}>
      <h3 className="gd-h"><Icon name="cal" /> {w.title}</h3>
      {body}
    </section>
  )
  const connectBtn = (label: string) => (
    <button type="button" className="rc-btn pri" disabled={busy} onClick={onConnect}>
      <Icon name="key" /> {label}
    </button>
  )
  const disconnect = can.disconnect ? (
    <button type="button" className="rc-btn gl-off" disabled={busy} onClick={onDisconnect}>
      <Icon name="power" /> {w.disconnect}
    </button>
  ) : null
  const remote = g.remote?.text ? (
    <span className="hint gl-why gd-hint" role="note" data-code={g.remote.code}><Icon name="monitor" /> {g.remote.text}</span>
  ) : null
  const lic = g.premium ? (
    <> {w.premium_lead} <AppLink className="gl-lic" href={g.premium.href}>{g.premium.label} ›</AppLink></>
  ) : null

  if (g.state === 'premium') {
    return box(
      <div className="gd-row">
        <span className="gl-mark plus"><Icon name="lock" /></span>
        <p className="gd-lines gd-l2">
          <b>{dot(g.why?.text ?? '')}</b>{g.why?.detail ? ` ${g.why.detail}` : ''}{lic}
        </p>
      </div>,
    )
  }

  if (g.waiting) {
    return box(
      <>
        <div className="gd-row">
          <span className="gl-mark"><Icon name="hourglass" /></span>
          <p className="gd-lines">
            <span className="gd-l1"><b>{w.waiting_title}</b></span>
            <span className="gd-l2">{w.waiting_detail}</span>
          </p>
        </div>
        <div className="gd-acts">
          {can.connect ? (
            <button type="button" className="rc-btn" disabled={busy} onClick={onConnect}>
              <Icon name="out" /> {w.reopen}
            </button>
          ) : null}
          <button type="button" className="rc-btn" disabled={busy} onClick={onCancel}>{w.cancel}</button>
        </div>
      </>,
    )
  }

  if (g.state === 'off') {
    return box(
      <>
        <p className="gd-lead">{w.lead}</p>
        <p className="gl-notice gd-notice">
          <Icon name="shield" />
          <span>
            {g.notice} {w.details}{' '}
            {/* страница сайта — чужой адрес: оболочка отдаёт его браузеру Windows */}
            <AppLink className="gl-det" href={g.privacy.href} target="_blank" rel="noopener">{g.privacy.label}</AppLink>
          </span>
        </p>
        <div className="gd-acts">
          {can.connect ? <>{connectBtn(w.connect)}<span className="hint gd-hint">{w.hint}</span></> : null}
          {/* со второго ПК кнопка видна выключенной: человек понимает, где подключать */}
          {!can.connect && remote ? (
            <><button type="button" className="rc-btn pri" disabled><Icon name="key" /> {w.connect}</button>{remote}</>
          ) : null}
        </div>
      </>,
      'gd-invite',
    )
  }

  /* подключён и все «связь есть»: кто, календарь, как дела; уровень — ссылкой на список Medici */
  const why = g.why
  const stopped = STOPPED.has(g.state)
  const calm = g.state === 'on' && !why
  const mark = calm ? 'ok' : stopped ? 'plus' : TONE[why?.tone ?? ''] ?? 'warn'
  const icon: IconName = calm ? 'check' : stopped ? 'lock' : 'excl'
  const last = g.last ? `${w.last_ok} ${g.last.when}` : ''
  const pending = g.pending > 0 ? `${w.pending} ${g.pending}` : ''
  let status: ReactNode
  if (calm) {
    status = [last, pending].filter(Boolean).join(' · ')
  } else {
    status = (
      <>
        <b>{lic ? dot(why?.text ?? '') : why?.text}</b>{why?.when ? ` (${why.when})` : ''}
        {why?.detail ? ` ${why.detail}` : ''}
        {g.state === 'on' && last ? ` ${last}.` : ''}
        {lic}
      </>
    )
  }
  return box(
    <>
      <div className="gd-row">
        <span className={`gl-mark ${mark}`}><Icon name={icon} /></span>
        <p className={`gd-lines${stopped ? ' gl-dim' : ''}`}>
          <span className="gd-l1">{w.connected} <b>{g.account}</b></span>
          {g.calendar ? <span className="gd-l2">{w.calendar_label} <b>„{g.calendar.name}”</b></span> : null}
        </p>
      </div>
      <div className="gd-stbox">
        <p className={`gd-status${calm ? '' : ` gd-st ${mark}`}`}>{status}</p>
        {/* только у спокойного: строки ошибки занимают это место, и высота блока остаётся той же */}
        {calm ? (
          <p className="gd-foot">
            <AppLink className="gd-lvl" href="/admin/medici">
              <Icon name="eye" /> {w.level_label} <b>{g.level.label}</b> ›
            </AppLink>
          </p>
        ) : null}
      </div>
      <div className="gd-acts">
        {can.connect && (g.state === 'reconnect' || g.state === 'foreign') ? connectBtn(w.reconnect) : null}
        {can.check ? (
          <button type="button" className="rc-btn gd-check" disabled={busy} onClick={onCheck}>
            <span className={`gl-ico${checking ? ' spin' : ''}`}><Icon name="refresh" /></span> {w.check}
          </button>
        ) : null}
        {disconnect}
        {!can.connect && !can.disconnect && remote}
      </div>
    </>,
    calm ? '' : 'gd-alert',
  )
}

/** Путь к оплате продолжает фразу сервера: без точки между ними вышла бы одна сбитая фраза. */
function dot(text: string): string {
  return text && !/[.!?…]$/.test(text) ? `${text}.` : text
}
