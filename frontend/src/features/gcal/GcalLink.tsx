import { useState, type ReactNode } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import type { IconName } from '../../components/icons'
import type { GcalGoogle } from './gcal'

/* Блок «Contul Google al clinicii» над полосой файла: состояние, кнопки (`can`) и все слова —
   сервера (gcal_link.view). Экран решает только раскладку и что раскрыто. */

interface Props {
  g: GcalGoogle
  busy: boolean
  /** Идёт «Verifică acum»: вращается значок, подпись кнопки та же — кнопка не меняет ширину. */
  checking: boolean
  onConnect: () => void
  onCancel: () => void
  onCalendar: (id: string) => Promise<boolean>
  onCheck: () => void
  onDisconnect: () => void
}

const TONE_MARK: Record<string, string> = { ok: 'ok', warn: 'warn', err: 'err' }

export function GcalLink({ g, busy, checking, onConnect, onCancel, onCalendar, onCheck, onDisconnect }: Props) {
  const [changing, setChanging] = useState(false)
  const w = g.words
  const can = g.can
  const remote = g.remote?.text ? (
    <span className="hint gl-why" role="note" data-code={g.remote.code}><Icon name="monitor" /> {g.remote.text}</span>
  ) : null
  const disconnect = can.disconnect ? (
    <button type="button" className="rc-btn gl-off" disabled={busy} onClick={onDisconnect}>
      <Icon name="power" /> {w.disconnect}
    </button>
  ) : null
  const check = can.check ? (
    <button type="button" className="rc-btn gl-check" disabled={busy} onClick={onCheck}>
      <span className={`gl-ico${checking ? ' spin' : ''}`}><Icon name="refresh" /></span> {w.check}
    </button>
  ) : null
  const connect = can.connect ? (
    <button type="button" className="rc-btn pri" disabled={busy} onClick={onConnect}>
      <Icon name="key" /> {w.connect}
    </button>
  ) : null

  if (g.waiting) {
    return (
      <div className="gl gl-row" data-gl="waiting">
        <span className="gl-mark"><Icon name="hourglass" /></span>
        <p className="gl-line">
          <span className="gl-h"><b>{w.waiting_title}</b></span>
          <span className="gl-d">{w.waiting_detail}</span>
        </p>
        <div className="gl-acts">
          {can.connect ? (
            <button type="button" className="rc-btn" disabled={busy} onClick={onConnect}>
              <Icon name="out" /> {w.reopen}
            </button>
          ) : null}
          <button type="button" className="rc-btn" disabled={busy} onClick={onCancel}>{w.cancel}</button>
        </div>
      </div>
    )
  }

  if (g.state === 'off') {
    return (
      <div className="gl gl-invite" data-gl="off">
        <div className="gl-top">
          <span className="gl-mark"><Icon name="cal" /></span>
          <div className="gl-ttl"><b>{w.title}</b><span>{w.lead}</span></div>
        </div>
        <p className="gl-notice">
          <Icon name="shield" />
          <span>
            {g.notice} {w.details}{' '}
            {/* страница сайта — чужой адрес: оболочка отдаёт его браузеру Windows */}
            <AppLink className="gl-det" href={g.privacy.href} target="_blank" rel="noopener">{g.privacy.label}</AppLink>
          </span>
        </p>
        <div className="gl-acts">
          {connect ? <>{connect}<span className="hint">{w.hint}</span></> : null}
          {/* со второго ПК кнопка видна выключенной: человек понимает, где подключать */}
          {!connect && g.remote ? (
            <><button type="button" className="rc-btn pri" disabled><Icon name="key" /> {w.connect}</button>{remote}</>
          ) : null}
        </div>
      </div>
    )
  }

  if (g.state === 'choose' || (changing && can.calendar)) {
    return (
      <Choose g={g} busy={busy} remote={remote} check={g.state === 'choose' ? check : null} disconnect={disconnect}
              onCancel={g.state === 'choose' ? null : () => setChanging(false)}
              onPick={async (id) => { if (await onCalendar(id)) setChanging(false) }} />
    )
  }

  /* Спокойные состояния — две строки, заголовок и подробность: опрос, переводящий «conectat»
     в «nu a reușit» и обратно, не меняет высоту полосы и не двигает список под ней. */
  const why = g.why
  const on = g.state === 'on'
  const mark = on && !why ? 'ok' : g.state === 'plus' || g.state === 'readonly' ? 'plus' : TONE_MARK[why?.tone ?? ''] ?? 'warn'
  const icon: IconName = on && !why ? 'check' : g.state === 'plus' || g.state === 'readonly' ? 'lock' : 'excl'
  const who = g.account || g.calendar ? (
    <>
      {w.connected} <b>{g.account}</b>
      {g.calendar ? <> · {w.calendar_label} <b>„{g.calendar.name}”</b></> : null}
    </>
  ) : null
  let head: ReactNode
  let detail: ReactNode
  if (on && !why) {
    head = (
      <>
        {who}
        {can.calendar ? <> <button type="button" className="dp-link gl-chg" disabled={busy}
                                   onClick={() => setChanging(true)}>{w.change}</button></> : null}
      </>
    )
    detail = g.last ? `${w.last_check} ${g.last.when}` : ''
  } else {
    const text = why?.text ?? ''
    // путь к Plus продолжает фразу сервера: без точки между ними вышла бы одна сбитая фраза
    const stop = g.plus && text && !/[.!?…]$/.test(text) ? '.' : ''
    head = <><b>{text}{stop}</b>{why?.when ? ` (${why.when})` : ''}{g.plus ? <> {w.plus_lead}{' '}
      <AppLink className="gl-lic" href={g.plus.href}>{g.plus.label} ›</AppLink></> : null}</>
    detail = why?.detail || (on && g.last ? `${w.last_ok} ${g.last.when}` : '')
  }
  // при Basic и режиме чтения живая связь видна приглушённо: она стоит, а не пропала
  const muted = (g.state === 'plus' || g.state === 'readonly') && g.connected && who
  return (
    <div className="gl gl-row" data-gl={g.state} data-tone={why?.tone ?? ''}>
      <span className={`gl-mark ${mark}`}><Icon name={icon} /></span>
      <p className="gl-line">
        <span className="gl-h">{head}</span>
        <span className="gl-d">{detail}</span>
        {muted ? <span className="gl-d gl-dim">{who}</span> : null}
      </p>
      <div className="gl-acts">
        {g.state === 'reconnect' ? connect : null}
        {check}
        {disconnect}
        {g.state !== 'plus' && g.state !== 'readonly' ? remote : null}
      </div>
    </div>
  )
}

interface ChooseProps {
  g: GcalGoogle
  busy: boolean
  remote: ReactNode
  check: ReactNode
  disconnect: ReactNode
  /** Только у «Schimbă»: закрыть выбор, оставив прежний календарь. */
  onCancel: (() => void) | null
  onPick: (id: string) => void
}

function Choose({ g, busy, remote, check, disconnect, onCancel, onPick }: ChooseProps) {
  const w = g.words
  /* Первый выбор ничего не отмечает: отмеченный основной календарь принимали не глядя, а записи клиники
     лежат в другом. У «Schimbă» отмечен текущий — человек меняет уже выбранное. */
  const cur = g.state === 'choose' ? '' : g.calendar?.id ?? ''
  const [pick, setPick] = useState(g.calendars.some((c) => c.id === cur) ? cur : '')
  const why = g.state === 'choose' ? g.why : null
  return (
    <div className="gl gl-pick" data-gl="choose">
      <span className={`gl-mark ${why ? TONE_MARK[why.tone] ?? 'warn' : 'ok'}`}><Icon name={why ? 'excl' : 'check'} /></span>
      <div className="gl-pickb">
        <p className="gl-line gl-who">
          {w.connected} <b>{g.account}</b>
          {why ? <span className="gl-d"><b>{why.text}</b>{why.detail ? ` ${why.detail}` : ''}</span> : null}
        </p>
        <div className="gl-cals" role="radiogroup" aria-label={w.calendar}>
          {g.calendars.map((c) => (
            <label key={c.id} className={`gl-cal${pick === c.id ? ' on' : ''}`}>
              <input type="radio" name="gl-cal" value={c.id} checked={pick === c.id}
                     disabled={busy || !g.can.calendar} onChange={() => setPick(c.id)} />
              <b>{c.name}</b>{c.primary ? <small>{w.primary}</small> : null}
            </label>
          ))}
        </div>
        <div className="gl-acts">
          {g.can.calendar ? (
            <button type="button" className="rc-btn pri" disabled={busy || !pick} onClick={() => onPick(pick)}>
              <Icon name="check" /> {w.calendar}
            </button>
          ) : null}
          {onCancel ? <button type="button" className="rc-btn" disabled={busy} onClick={onCancel}>{w.cancel}</button> : null}
          {check}
          {disconnect}
          {remote}
        </div>
      </div>
    </div>
  )
}
