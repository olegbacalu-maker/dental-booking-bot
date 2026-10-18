import { useCallback, useState, type FormEvent } from 'react'
import { AppLink } from '../../components/AppLink'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError, type ApiResult } from '../../services/api'
import { settings, type SmsData, type SmsOrder, type SmsSettingsForm } from './settings'

/* Setări › SMS (S6, docs/dentpilot-2/sms.md › «Экраны»). Видит и регистратура:
   переключатели событий, час, вариант текста и строку телефона может менять
   любой вошедший (слово Олега 16.10); «Comandă» — пополнение и своё имя — и
   тестовая SMS только директору (`can_order` с сервера, отказ — `api_require`).
   ⛔ Тексты клиника НЕ правит: выбирает готовый вариант и видит предпросмотр
   со своим названием; число сегментов считает сервер. Каждое изменение
   сохраняется сразу — ответ приносит свежие данные и предпросмотры. */
const T = {
  title: 'SMS pentru pacienți',
  sub: 'memento-uri despre vizita programată, trimise în numele clinicii',
  offline: 'Programul nu răspunde. Reîncercați.',
  unavailable: 'Memento-urile SMS sunt disponibile doar în programul activat cu licență.',
  notOffered: 'Pachetul SMS nu este încă disponibil pentru clinica dvs. — scrieți-ne și îl pornim.',
  offByClinic: 'Serviciul SMS este oprit la cererea clinicii.',
  resume: 'Pentru reluare, contactați-ne:',
  stateTitle: 'Starea pachetului',
  balance: 'SMS rămase',
  from: 'expeditor',
  queued: 'în așteptare',
  today: 'trimise azi',
  delivered: 'livrate azi',
  failed: 'nereușite azi',
  lastAt: 'ultima verificare',
  check: 'Verifică acum',
  eventsTitle: 'Ce memento-uri se trimit',
  dayBefore: 'Cu o zi înainte',
  dayBeforeHint: 'în ultima zi lucrătoare dinaintea vizitei, de la ora',
  sameDay: 'În ziua vizitei',
  sameDayHint: 'cu',
  hours1: 'o oră înainte',
  hoursN: '{n} ore înainte',
  variant: 'textul',
  phoneLine: 'adaugă rândul „Anulare: {phone}" cu telefonul clinicii',
  phoneLineNoPhone: 'rândul cu telefonul clinicii — completați telefonul în Setări › Clinica',
  previewRo: 'română',
  previewRu: 'русский',
  segments1: '1 SMS',
  segmentsN: '{n} SMS pe memento',
  previewHint: 'Textele sunt stabilite de DentPilot (un singur SMS, fără date despre tratament); limba — din fișa pacientului. Text propriu — la cerere, scrieți-ne.',
  forecastTitle: 'Consum estimat',
  forecast: '~{month} SMS pe lună ({visits} vizite cu telefon în ultimele 30 de zile)',
  forecastLeft: ' · restul ajunge pentru ~{days} zile',
  forecastNone: 'Încă nu sunt vizite pentru estimare.',
  orderTitle: 'Comandă',
  orderHint: 'Nota de plată vine pe e-mailul clinicii; după plată SMS-urile se adaugă automat.',
  packBtn: '{units} SMS — {price} MDL',
  packConfirm: 'Comandați {units} SMS pentru {price} MDL? Nota de plată vine pe e-mail.',
  packNone: 'Pachetele nu sunt încă disponibile.',
  ordered: 'Nota {ref} ({amount} MDL) a fost emisă și trimisă pe e-mail.',
  orderedPay: 'Plătește cu cardul',
  senderTitle: 'Numele expeditorului',
  senderNone: 'SMS-urile pleacă de la numele „DentPilot" cu denumirea clinicii în text. Puteți cere numele propriu (până la 11 caractere latine).',
  senderRequested: 'cerere trimisă — descărcați cererea completată în contul clinicii (cloud.dentpilot.md/cont), semnați-o și încărcați-o acolo',
  senderSubmitted: 'la operatori: 1–2 zile lucrătoare',
  senderActive: 'activ',
  senderRejected: 'respins',
  senderUntil: 'plătit până la {date}',
  senderPh: 'Numele (ex. ZambetDent)',
  senderBtn: 'Cere numele',
  senderNameBtn: 'Comandă numele — {price} MDL / an',
  senderNameConfirm: 'Comandați numele propriu de expeditor pentru un an ({price} MDL)?',
  testTitle: 'SMS de test',
  testHint: 'Pe numărul dvs. mobil, din pachetul clinicii.',
  testPh: 'Telefon mobil',
  testBtn: 'Trimite',
  directorOnly: 'Comanda și testul — doar directorul.',
} as const

const SENDER: Record<string, string> = {
  requested: T.senderRequested, submitted: T.senderSubmitted, active: T.senderActive, rejected: T.senderRejected,
}

interface Props {
  navigate?: (url: string) => void
}

/** Данные экрана грузит роутер (B2.2), App.tsx › LOADS. */
export const loadSmsSettings: RouteLoad<SmsData> = (signal) => settings.sms(signal)

export function SmsSettingsScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<SmsData>(navigate)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [busy, setBusy] = useState(false)
  const [sender, setSender] = useState('')
  const [phone, setPhone] = useState('')
  const [order, setOrder] = useState<SmsOrder | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

  function fail(e: unknown) {
    const err = asApiError(e)
    if (leaveIfSignedOut(err)) return
    setToast({ tone: 'err', text: err.text || T.offline })
  }
  const said = (r: ApiResult<unknown>) => { if (r.text) setToast({ tone: r.tone, text: r.text }) }

  async function run<T>(fn: () => Promise<ApiResult<T>>, after?: (r: ApiResult<T>) => void) {
    setBusy(true)
    try {
      const r = await fn()
      after?.(r)
      said(r)
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  const data: SmsData | null = state.status === 'ready' ? state.data : null

  /* Переключатель сохраняется сразу: ответ — свежие данные с предпросмотрами. */
  function save(patch: (f: SmsSettingsForm) => SmsSettingsForm) {
    if (!data) return
    void run(() => settings.smsSave(patch(data.settings)), (r) => replace(r.data))
  }

  async function orderPack(units: number, price: number) {
    const text = T.packConfirm.replace('{units}', String(units)).replace('{price}', String(price))
    if (!await ask({ text, ok: T.orderTitle })) return
    void run(() => settings.smsOrder(units), (r) => setOrder(r.data))
  }

  async function orderName(price: number) {
    if (!await ask({ text: T.senderNameConfirm.replace('{price}', String(price)), ok: T.orderTitle })) return
    void run(() => settings.smsOrderName(), (r) => setOrder(r.data))
  }

  function requestSender(e: FormEvent) {
    e.preventDefault()
    void run(() => settings.smsSender(sender), (r) => { replace(r.data); setSender('') })
  }

  function sendTest(e: FormEvent) {
    e.preventDefault()
    void run(() => settings.smsTest(phone), () => setPhone(''))
  }

  if (state.status === 'leaving') return null
  if (state.status === 'failed') {
    return (
      <section className="dp-react-root">
        <h2><Icon name="chat" /> {T.title}</h2>
        <LoadFailed error={state.error} onRetry={retry} />
      </section>
    )
  }

  const s = data?.settings
  const acc = data?.account ?? null
  const seg = (n: number) => (n <= 1 ? T.segments1 : T.segmentsN.replace('{n}', String(n)))
  const preview = (event: string, variant: string) => {
    const p = data?.previews[event]?.[variant]
    if (!p) return null
    return (
      <div className="dp-sms-preview">
        {(['ro', 'ru'] as const).map((lang) => p[lang] ? (
          <div key={lang} className="dp-sms-pv">
            <small className="dp-muted">{lang === 'ro' ? T.previewRo : T.previewRu} · {seg(p[lang].segments)}</small>
            <pre>{p[lang].text}</pre>
          </div>
        ) : null)}
      </div>
    )
  }

  return (
    <section className="dp-react-root" aria-busy={data === null}>
      <h2><Icon name="chat" /> {T.title}</h2>
      <p className="hint">{T.sub}</p>

      {data && !data.available && <div className="banner warn" role="status">{T.unavailable}</div>}
      {data && data.available && !data.offered && (
        <div className="banner warn" role="status">{T.notOffered}{data.why ? ` (${data.why})` : ''}</div>
      )}
      {/* «Выключить» в облаке = клиника отказалась (Олег 17.10): не ошибка, а состояние с путём назад */}
      {data && data.offered && data.blocked === 'sms_off' && (
        <div className="banner warn" role="status">
          <b>{T.offByClinic}</b> {T.resume} {data.support.phone} · {data.support.email}
        </div>
      )}
      {data && data.offered && !data.enabled && data.why && data.blocked !== 'sms_off' && (
        <div className="banner err" role="alert">{data.why}</div>
      )}
      {/* «мало SMS» — слова сервера (`sms_loop.low`): одно правило по штукам на
          этот баннер, пункт меню и уведомление у часов, без «дней» */}
      {data?.low && (
        <div className="banner warn" role="status">
          <b>{data.low.title}.</b> {data.low.text}
        </div>
      )}

      {data?.offered && acc && (
        <>
          <h3>{T.stateTitle}</h3>
          <div className="pl-stats dp-sms-state">
            <div className="pl-stat"><b>{acc.balance}</b><small>{T.balance}</small></div>
            <div className="pl-stat"><b>{acc.from || '—'}</b><small>{T.from}</small></div>
            <div className="pl-stat"><b>{data.counts.queued}</b><small>{T.queued}</small></div>
            <div className="pl-stat"><b>{data.counts.today}</b><small>{T.today}</small></div>
            <div className="pl-stat"><b>{data.counts.delivered}</b><small>{T.delivered}</small></div>
            <div className="pl-stat"><b>{data.counts.failed}</b><small>{T.failed}</small></div>
          </div>
          <p className="hint">
            {T.lastAt}: {data.last.at ? data.last.at.replace('T', ' ').slice(0, 16) : '—'}
            {data.last.error_text ? ` · ${data.last.error_text}` : ''}
            {' '}
            <button type="button" className="dp-link" disabled={busy}
              onClick={() => void run(() => settings.smsRefresh(), (r) => replace(r.data))}>
              <Icon name="refresh" /> {T.check}
            </button>
          </p>
        </>
      )}

      {data && s && data.available && (
        <>
          <h3>{T.eventsTitle}</h3>
          <div className="dp-sms-events">
            <div className="dp-sms-ev">
              <label>
                <input type="checkbox" checked={s.day_before.on} disabled={busy}
                  onChange={(e) => save((f) => ({ ...f, day_before: { ...f.day_before, on: e.target.checked } }))} />
                {' '}<b>{T.dayBefore}</b>
              </label>
              <span className="dp-muted">{T.dayBeforeHint}</span>
              <select value={s.day_before.hour} disabled={busy} aria-label={T.dayBefore + ' — ora'}
                onChange={(e) => save((f) => ({ ...f, day_before: { ...f.day_before, hour: Number(e.target.value) } }))}>
                {data.options.hours.map((h) => <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>)}
              </select>
              <span className="dp-muted">{T.variant}</span>
              <select value={s.day_before.variant} disabled={busy} aria-label={T.dayBefore + ' — textul'}
                onChange={(e) => save((f) => ({ ...f, day_before: { ...f.day_before, variant: e.target.value } }))}>
                {data.options.variants.map((v) => <option key={v.key} value={v.key}>{v.label}</option>)}
              </select>
            </div>
            {s.day_before.on && preview('day_before', s.day_before.variant)}
            <div className="dp-sms-ev">
              <label>
                <input type="checkbox" checked={s.same_day.on} disabled={busy}
                  onChange={(e) => save((f) => ({ ...f, same_day: { ...f.same_day, on: e.target.checked } }))} />
                {' '}<b>{T.sameDay}</b>
              </label>
              <span className="dp-muted">{T.sameDayHint}</span>
              <select value={s.same_day.hours} disabled={busy} aria-label={T.sameDay + ' — cu câte ore înainte'}
                onChange={(e) => save((f) => ({ ...f, same_day: { ...f.same_day, hours: Number(e.target.value) } }))}>
                {data.options.leads.map((h) => (
                  <option key={h} value={h}>{h === 1 ? T.hours1 : T.hoursN.replace('{n}', String(h))}</option>
                ))}
              </select>
              <span className="dp-muted">{T.variant}</span>
              <select value={s.same_day.variant} disabled={busy} aria-label={T.sameDay + ' — textul'}
                onChange={(e) => save((f) => ({ ...f, same_day: { ...f.same_day, variant: e.target.value } }))}>
                {data.options.variants.map((v) => <option key={v.key} value={v.key}>{v.label}</option>)}
              </select>
            </div>
            {s.same_day.on && preview('same_day', s.same_day.variant)}
            <div className="dp-sms-ev">
              <label>
                <input type="checkbox" checked={s.phone_line} disabled={busy || !data.clinic.phone}
                  onChange={(e) => save((f) => ({ ...f, phone_line: e.target.checked }))} />
                {' '}{data.clinic.phone ? T.phoneLine.replace('{phone}', data.clinic.phone) : T.phoneLineNoPhone}
              </label>
            </div>
          </div>
          <p className="hint">{T.previewHint}</p>

          <h3>{T.forecastTitle}</h3>
          <p className="hint">
            {data.forecast.visits > 0
              ? T.forecast.replace('{month}', String(data.forecast.month)).replace('{visits}', String(data.forecast.visits))
                + (data.forecast.days_left !== null && acc ? T.forecastLeft.replace('{days}', String(data.forecast.days_left)) : '')
              : T.forecastNone}
          </p>
        </>
      )}

      {data?.offered && acc && (
        <>
          <h3>{T.senderTitle}</h3>
          {acc.sender_state === 'none' || !acc.sender ? (
            <p className="hint">{T.senderNone}</p>
          ) : (
            <p className="hint">
              <b>{acc.sender}</b> — {SENDER[acc.sender_state] ?? acc.sender_state}
              {acc.sender_note ? ` (${acc.sender_note})` : ''}
              {acc.sender_until ? ` · ${T.senderUntil.replace('{date}', acc.sender_until.slice(0, 10))}` : ''}
            </p>
          )}
          {data.can_order ? (
            <>
              {(acc.sender_state === 'none' || acc.sender_state === 'rejected') && (
                <form className="add" onSubmit={requestSender}>
                  <input value={sender} placeholder={T.senderPh} aria-label={T.senderPh} maxLength={11} required
                    style={{ width: 220 }} disabled={busy} onChange={(e) => setSender(e.target.value)} />
                  <button disabled={busy}>{T.senderBtn}</button>
                </form>
              )}
              {acc.sender_state !== 'none' && acc.name_price > 0 && (
                <p className="dp-actions">
                  <button type="button" className="savebtn" disabled={busy} onClick={() => void orderName(acc.name_price)}>
                    <Icon name="card" /> {T.senderNameBtn.replace('{price}', String(acc.name_price))}
                  </button>
                </p>
              )}

              <h3>{T.orderTitle}</h3>
              <p className="hint">{T.orderHint}</p>
              {acc.packs.length ? (
                <p className="dp-actions">
                  {acc.packs.map((p) => (
                    <button key={p.units} type="button" className="savebtn" disabled={busy}
                      onClick={() => void orderPack(p.units, p.price)}>
                      <Icon name="cash" /> {T.packBtn.replace('{units}', String(p.units)).replace('{price}', String(p.price))}
                    </button>
                  ))}
                </p>
              ) : <p className="hint">{T.packNone}</p>}
              {order && (
                <div className="banner ok" role="status">
                  {T.ordered.replace('{ref}', order.reference).replace('{amount}', String(order.amount))}
                  {/* страница оплаты maib — чужой адрес: AppLink отдаёт обычную ссылку,
                      target=_blank уводит её в системный браузер, как «Plătește acum» */}
                  {order.pay_url ? <> <AppLink href={order.pay_url} target="_blank" rel="noopener">{T.orderedPay}</AppLink></> : null}
                </div>
              )}

              <h3>{T.testTitle}</h3>
              <p className="hint">{T.testHint}</p>
              <form className="add" onSubmit={sendTest}>
                <input value={phone} placeholder={T.testPh} aria-label={T.testPh} inputMode="tel" required
                  style={{ width: 200 }} disabled={busy} onChange={(e) => setPhone(e.target.value)} />
                <button disabled={busy}>{T.testBtn}</button>
              </form>
            </>
          ) : <p className="hint">{T.directorOnly}</p>}
        </>
      )}
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
