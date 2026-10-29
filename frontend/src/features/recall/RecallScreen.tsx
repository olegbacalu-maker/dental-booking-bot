import { useEffect, useRef, useState } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { hideDialog, showDialog } from '../patients/card/dialog'
import { dmy, letter, mailto, recallApi, type RecallData, type RecallResult, type RecallRow, type RecallTab } from './recall'

/* «Rechemări» (29.10) — список регистратуры: кому пора на повторную
   процедуру (срок задан у услуги), позвонить или написать. Решения Олега
   29.10 (В1–В5 = А): врач экрана не видит; строка за 14 дней до срока;
   статистики нет; кадры — design/rechemari (К1–К3, К7).
   ⛔ Правило списка и слова просрочки/отметки — сервера; здесь только
   вкладки, фильтр и действия. Экран не живой поверхности (как Statistici):
   после отметки перечитывает `GET /api/recall` (`retry`). Письмо — только
   `mailto:` + «Copiază»: без настроенной почты Windows может не открыть
   ничего, и копирование — рабочий путь, не запасной (план § 3).
   SMS (30.10, план review/plan-recall-sms, Олег «все А»): кнопка в строке
   только при `d.sms` (Plus/пробный + галочка в Setări › SMS — решает
   сервер), текст и сегменты — сервера, окно подтверждения с остатком, одна
   SMS на цикл (вторую сервер не шлёт), после ответа — перечитать. */
const T = {
  tabs: { due: 'De sunat', snoozed: 'Amânate', stop: 'Nu mai reaminti' } as Record<RecallTab, string>,
  tracked: 'Servicii urmărite',
  months: 'luni',
  statMonth: 'Luna aceasta',
  statPrev: 'luna trecută',
  statContacted: 'contactați',
  statBooked: 'programați',
  all: 'Toate serviciile',
  last: 'ultima',
  booked: 'vine pe',
  tell: 'spuneți atunci',
  call: 'Sună',
  mail: 'E-mail',
  noMail: 'fără e-mail',
  sms: 'SMS',
  smsWhy: {
    sms_off: 'pacientul a refuzat memento-urile SMS',
    phone: 'numărul nu este un mobil din Moldova',
    no_clinic_phone: 'completați telefonul clinicii în Setări › Clinica',
    quiet: 'SMS-urile se trimit între 08:00 și 21:00',
  } as Record<string, string>,
  smsTitle: 'SMS pacientului',
  smsTo: 'Către',
  smsText: 'Textul',
  smsSeg1: '1 SMS',
  smsSegN: '{n} SMS',
  smsLeft: 'rămân {n} în pachet',
  smsHint: 'Textul este stabilit de DentPilot — fără numele pacientului, serviciu sau prețuri. '
    + 'Se trimite un singur SMS pentru acest termen; pentru a doua reamintire sunați.',
  smsSend: 'Trimite SMS',
  mark: 'Marchează',
  m: {
    contacted: 'Sunat — revine',
    contactedHint: 'ascunde 14 zile',
    noanswer: 'Nu răspunde',
    noanswerHint: 'rămâne în listă',
    later: 'Amânat până la',
    stop: 'Nu mai reaminti',
    stopFor: 'pentru',
    clear: 'Anulează marcajul',
  },
  ok: 'OK',
  until: 'până la',
  times: '×',
  emptyNone: 'Niciun serviciu nu are termen de rechemare.',
  emptyNoneHint: 'Directorul alege termenul la fiecare serviciu (de exemplu Igienizare — 6 luni). '
    + 'Pacienții cu serviciul finalizat apar aici singuri, când se apropie termenul.',
  emptyNoneGo: 'Deschide Setări › Servicii',
  emptyNoneAsk: 'Cereți directorului să aleagă termenul în Setări › Servicii.',
  emptyDue: 'Nimeni de sunat acum.',
  emptyDueHint: 'Lista se completează din vizitele finalizate. Istoricul de pe hârtie: adăugați vizita '
    + 'trecută în agendă cu bifa „Vizita a avut loc”.',
  emptyTab: '— nimic aici —',
  mailTitle: 'E-mail pacientului',
  to: 'Către',
  subject: 'Subiect',
  open: 'Deschide în programul de e-mail',
  copyTo: 'Copiază adresa',
  copyBody: 'Copiază textul',
  copied: 'Copiat',
  mailHint: 'Scrisoarea pleacă din e-mailul clinicii — DentPilot nu trimite nimic prin internet. '
    + 'Dacă nu se deschide nimic, copiați adresa și textul în Gmail sau Outlook.',
  sent: 'Am trimis — marchează „E-mail trimis”',
  close: 'Închide',
  offline: 'Programul nu răspunde. Reîncercați.',
} as const

export const loadRecall: RouteLoad<RecallData> = (signal) => recallApi.get(signal)

interface Props {
  navigate?: (url: string) => void
}

export function RecallScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, leaveIfSignedOut } = useRouteLoad<RecallData>(navigate)
  const [tab, setTab] = useState<RecallTab>('due')
  const [svc, setSvc] = useState('')
  const [menu, setMenu] = useState<string | null>(null)
  const [mailRow, setMailRow] = useState<RecallRow | null>(null)
  const [smsRow, setSmsRow] = useState<RecallRow | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)

  /* меню отметок закрывается щелчком мимо и Esc */
  useEffect(() => {
    if (!menu) return
    const off = (e: MouseEvent) => {
      if (!(e.target as Element | null)?.closest('.rc-mk')) setMenu(null)
    }
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(null) }
    document.addEventListener('mousedown', off)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', off); document.removeEventListener('keydown', key) }
  }, [menu])

  if (state.status === 'leaving') return null
  if (state.status === 'failed') {
    return <section className="dp-react-root"><LoadFailed error={state.error} onRetry={retry} /></section>
  }
  if (state.status === 'loading') {
    return <section className="dp-react-root" aria-busy="true"><div className="fcard" /></section>
  }
  const d = state.data

  async function mark(r: RecallRow, result: RecallResult, until = '') {
    setBusy(true)
    try {
      const res = await recallApi.mark(r.pid, r.service_id, result, until)
      if (res.text) setToast({ tone: res.tone, text: res.text })
      setMenu(null)
      retry()
    } catch (e) {
      const err = asApiError(e)
      if (leaveIfSignedOut(err)) return
      setToast({ tone: 'err', text: err.text || T.offline })
    } finally {
      setBusy(false)
    }
  }

  /* SMS: отметку ставит сервер после ответа; отказ — его словами; список
     перечитывается и при отказе (dup/quiet значат, что экран устарел) */
  async function sendSms(r: RecallRow) {
    setBusy(true)
    try {
      const res = await recallApi.sms(r.pid, r.service_id)
      if (res.text) setToast({ tone: res.tone, text: res.text })
      setSmsRow(null)
      retry()
    } catch (e) {
      const err = asApiError(e)
      if (leaveIfSignedOut(err)) return
      setSmsRow(null)
      setToast({ tone: 'err', text: err.text || T.offline })
      retry()
    } finally {
      setBusy(false)
    }
  }

  if (!d.services.length) {
    /* кадр К7а: ни у одной услуги нет срока — факт и дверь к настройке */
    return (
      <section className="dp-react-root">
        <div className="fcard rc-empty">
          <span className="rc-empty-ico"><Icon name="refresh" /></span>
          <b>{T.emptyNone}</b>
          <p className="hint">{T.emptyNoneHint}</p>
          {d.can_settings
            ? <AppLink className="rc-btn pri" href="/admin/settings/services">{T.emptyNoneGo}</AppLink>
            : <p className="hint">{T.emptyNoneAsk}</p>}
        </div>
      </section>
    )
  }

  const rows = d.rows.filter((r) => r.tab === tab && (!svc || r.service_id === svc))
  return (
    <section className="dp-react-root rc">
      <div className="fcard rc-head">
        <div className="rc-tabs" role="tablist">
          {(['due', 'snoozed', 'stop'] as RecallTab[]).map((k) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k}
              className={`rc-tab${tab === k ? ' on' : ''}`} onClick={() => setTab(k)}>
              {T.tabs[k]} <span className={`rc-n${k === 'due' && d.counts.due ? ' hot' : ''}`}>{d.counts[k]}</span>
            </button>
          ))}
        </div>
        <div className="rc-tools">
          {/* значение из конфига, не описание (правило 21.09: факт вместо текста) */}
          <span className="hint rc-tracked">{T.tracked}: {d.services.map((s) => `${s.ro} (${s.months} ${T.months})`).join(' · ')}</span>
          {d.services.length > 1 && (
            <select value={svc} onChange={(e) => setSvc(e.target.value)} aria-label={T.all}>
              <option value="">{T.all}</option>
              {d.services.map((s) => <option key={s.id} value={s.id}>{s.ro}</option>)}
            </select>
          )}
        </div>
        {/* статистика одной строкой (В4 → Б, Олег 29.10): цифры — сервера;
            без единой отметки сервер шлёт null — нулей не рисуем */}
        {d.stats && (
          <p className="hint rc-stats">
            <b>{T.statMonth}:</b> {T.statContacted} {d.stats.month.contacted} · {T.statBooked} {d.stats.month.booked}
            {' · '}{T.statPrev}: {d.stats.prev.contacted} · {d.stats.prev.booked}
          </p>
        )}
      </div>

      {!rows.length ? (
        <div className="fcard rc-empty">
          {tab === 'due' ? (
            /* кадр К7б: срок есть, звонить некому — откуда берётся список */
            <>
              <span className="rc-empty-ico"><Icon name="check" /></span>
              <b>{T.emptyDue}</b>
              <p className="hint">{T.emptyDueHint}</p>
            </>
          ) : <p className="hint">{T.emptyTab}</p>}
        </div>
      ) : (
        <div className="fcard rc-list">
          {rows.map((r) => {
            const key = `${r.pid}:${r.service_id}`
            return (
              <div key={key} className={`rc-row${r.mark?.result === 'noanswer' ? ' dim' : ''}`} data-pid={r.pid}>
                <div className="rc-who">
                  <AppLink href={`/admin/patient/${r.pid}`}><b>{r.name}</b></AppLink>
                  <small>{r.phone || '—'}{r.email ? ` · ${r.email}` : ''}</small>
                </div>
                <div className="rc-what">
                  <b>{r.service}</b>
                  <small>{T.last} {dmy(r.last_at)}{r.doctor ? ` · ${r.doctor}` : ''}</small>
                </div>
                <div className="rc-when">
                  <b className="num">~{dmy(r.due)}</b>
                  <span className={`rc-late ${r.late_days > 0 ? 'bad' : 'soon'}`}>{r.late}</span>
                </div>
                <div className="rc-notes">
                  {r.booked && (
                    <span className="rc-pill blue"><Icon name="cal" /> {T.booked} {r.booked.date} ({r.booked.service}) — {T.tell}</span>
                  )}
                  {r.mark && <MarkPill mark={r.mark} />}
                </div>
                <div className="rc-acts">
                  {r.phone && <AppLink className="rc-btn" href={`tel:${r.phone}`}><Icon name="phone" /> {T.call}</AppLink>}
                  <button type="button" className="rc-btn" disabled={!r.email} title={r.email ? '' : T.noMail}
                    onClick={() => setMailRow(r)}><Icon name="mail" /> {T.mail}</button>
                  {/* кнопка SMS — только когда сервер дал блок (Plus и галочка) и
                      SMS этого цикла ещё не ушла; причина отказа — подсказкой */}
                  {d.sms && r.sms && (() => {
                    const why = !r.sms.can ? (r.sms.why ?? '') : d.sms.quiet ? 'quiet' : ''
                    return (
                      <button type="button" className="rc-btn" disabled={!!why} title={why ? T.smsWhy[why] ?? why : ''}
                        onClick={() => setSmsRow(r)}><Icon name="chat" /> {T.sms}</button>
                    )
                  })()}
                  <span className="rc-mk">
                    <button type="button" className="rc-btn pri" aria-expanded={menu === key} aria-haspopup="menu"
                      onClick={() => setMenu(menu === key ? null : key)}>{T.mark} <Icon name="caret-d" /></button>
                    {menu === key && <MarkMenu r={r} busy={busy} onMark={(res, u) => { void mark(r, res, u) }} />}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}
      <MailDialog row={mailRow} clinic={d.clinic} onClose={() => setMailRow(null)}
        onSent={(r) => { setMailRow(null); void mark(r, 'emailed') }} />
      {d.sms && <SmsDialog row={smsRow} balance={d.sms.balance} busy={busy} onClose={() => setSmsRow(null)}
        onSend={(r) => { void sendSms(r) }} />}
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={() => setToast(null)} />}
    </section>
  )
}

function MarkPill({ mark }: { mark: NonNullable<RecallRow['mark']> }) {
  /* отметка sms: слово доставки сервера; недоставленная — янтарная (строка
     уже вернулась в «De sunat», сервер решил) */
  const bad = mark.result === 'sms' && (mark.sms?.state === 'undelivered' || mark.sms?.state === 'failed')
  const tone = mark.result === 'noanswer' || bad ? 'amber' : mark.result === 'stop' ? 'grey' : 'green'
  const icon = mark.result === 'noanswer' ? 'phone-off' : mark.result === 'emailed' ? 'mail'
    : mark.result === 'sms' ? 'chat' : mark.result === 'stop' ? 'ban' : mark.result === 'later' ? 'clock' : 'check'
  const word = mark.result === 'sms' && mark.sms?.word ? mark.sms.word : mark.word
  return (
    <span className={`rc-pill ${tone}`}>
      <Icon name={icon} />
      {' '}{word}{mark.result === 'noanswer' && mark.n_noanswer > 1 ? ` ${T.times}${mark.n_noanswer}` : ''}
      {mark.until && mark.result !== 'noanswer' && !bad ? ` · ${T.until} ${dmy(mark.until)}` : ''}
      {' · '}{mark.at}{mark.actor ? ` ${mark.actor}` : ''}
    </span>
  )
}

/** Окно SMS (30.10): кому, текст сервера, сколько SMS и сколько останется,
 *  «Trimite SMS». Текст не правится: его пишет DentPilot. */
function SmsDialog({ row, balance, busy, onClose, onSend }: {
  row: RecallRow | null; balance: number; busy: boolean; onClose: () => void; onSend: (r: RecallRow) => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    if (row) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [row])
  const s = row?.sms ?? null
  const segs = s?.segments ?? 1
  return (
    <dialog ref={ref} className="rc-mail rc-sms" onClose={onClose}>
      <div className="dlg-head">
        <span><Icon name="chat" /> {T.smsTitle}</span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      {row && s && (
        <div className="rc-mail-b">
          <dl className="rc-mail-f">
            <dt>{T.smsTo}</dt><dd><b>{row.name}</b> {row.phone}</dd>
            <dt>{T.smsText}</dt><dd className="hint">{segs <= 1 ? T.smsSeg1 : T.smsSegN.replace('{n}', String(segs))}
              {' · '}{T.smsLeft.replace('{n}', String(Math.max(0, balance - segs)))}</dd>
          </dl>
          <pre className="rc-mail-t">{s.text}</pre>
          <p className="hint">{T.smsHint}</p>
          <div className="rc-mail-a">
            <button type="button" className="dp-btn pri" disabled={busy} onClick={() => onSend(row)}>
              <Icon name="chat" /> {T.smsSend}</button>
            <button type="button" className="rc-btn" disabled={busy} onClick={onClose}>{T.close}</button>
          </div>
        </div>
      )}
    </dialog>
  )
}

/** Меню отметок (кадр К2): слова — как на кадре, решение Олега 29.10. */
function MarkMenu({ r, busy, onMark }: { r: RecallRow; busy: boolean; onMark: (res: RecallResult, until?: string) => void }) {
  /* дата по умолчанию — через месяц от срока или от сегодня (что позже);
     «сегодня» здесь — день срока + просрочка: сервер дал обе без «сейчас» */
  const [until, setUntil] = useState(() => {
    const base = new Date(r.due)
    base.setDate(base.getDate() + Math.max(r.late_days, 0) + 30)
    return base.toISOString().slice(0, 10)
  })
  return (
    <div className="rc-menu" role="menu">
      <button type="button" role="menuitem" disabled={busy} onClick={() => onMark('contacted')}>
        <Icon name="check" /> {T.m.contacted}<small>{T.m.contactedHint}</small></button>
      <button type="button" role="menuitem" disabled={busy} onClick={() => onMark('noanswer')}>
        <Icon name="phone-off" /> {T.m.noanswer}<small>{T.m.noanswerHint}</small></button>
      <div className="rc-menu-later">
        <span><Icon name="clock" /> {T.m.later}</span>
        <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} aria-label={T.m.later} />
        <button type="button" className="savebtn" disabled={busy || !until} onClick={() => onMark('later', until)}>{T.ok}</button>
      </div>
      <button type="button" role="menuitem" className="bad" disabled={busy} onClick={() => onMark('stop')}>
        <Icon name="ban" /> {T.m.stop}<small>{T.m.stopFor} {r.service.toLowerCase()}</small></button>
      {r.mark && (
        <button type="button" role="menuitem" disabled={busy} onClick={() => onMark('clear')}>
          <Icon name="undo" /> {T.m.clear}</button>
      )}
    </div>
  )
}

/** Окно письма (кадр К3): текст, `mailto:`, «Copiază», отметка — человеком. */
function MailDialog({ row, clinic, onClose, onSent }: {
  row: RecallRow | null; clinic: RecallData['clinic']; onClose: () => void; onSent: (r: RecallRow) => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const [copied, setCopied] = useState('')
  useEffect(() => {
    if (row) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [row])
  const l = row ? letter(row, clinic) : null
  function copy(what: string, text: string) {
    if (navigator.clipboard) void navigator.clipboard.writeText(text)
    setCopied(what)
    window.setTimeout(() => setCopied(''), 1200)
  }
  return (
    <dialog ref={ref} className="wide rc-mail" onClose={onClose}>
      <div className="dlg-head">
        <span><Icon name="mail" /> {T.mailTitle}</span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      {row && l && (
        <div className="rc-mail-b">
          <dl className="rc-mail-f">
            <dt>{T.to}</dt><dd><b>{row.name}</b> &lt;{row.email}&gt;</dd>
            <dt>{T.subject}</dt><dd>{l.subject}</dd>
          </dl>
          <pre className="rc-mail-t">{l.body}</pre>
          <div className="rc-mail-a">
            {/* `mailto:` — не адрес экрана: AppLink отдаёт его документу, оболочка — Windows */}
            <AppLink className="dp-btn pri" href={mailto(row.email, l)}><Icon name="mail" /> {T.open}</AppLink>
            <button type="button" className="rc-btn" onClick={() => copy('to', row.email)}>
              <Icon name="clip" /> {copied === 'to' ? T.copied : T.copyTo}</button>
            <button type="button" className="rc-btn" onClick={() => copy('body', `${l.subject}\n\n${l.body}`)}>
              <Icon name="clip" /> {copied === 'body' ? T.copied : T.copyBody}</button>
          </div>
          <p className="hint">{T.mailHint}</p>
          <button type="button" className="rc-btn rc-sent" onClick={() => onSent(row)}>
            <Icon name="check" /> {T.sent}</button>
        </div>
      )}
    </dialog>
  )
}
