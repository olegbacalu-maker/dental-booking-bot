import { useCallback, useState, type FormEvent } from 'react'
import { AppLink } from '../../components/AppLink'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError, type ApiResult } from '../../services/api'
import { roCount } from '../../utils/plural'
import {
  settings, type SmsData, type SmsNote, type SmsOrder, type SmsPreview, type SmsSettingsForm, type SmsVariant,
} from './settings'

/* Setări › SMS (S6, docs/dentpilot-2/sms.md › «Экраны»). Видит и регистратура:
   переключатели событий, час, вариант текста и строку телефона может менять
   любой вошедший (слово Олега 16.10); «Comandă» — пополнение и своё имя — и
   тестовая SMS только директору (`can_order` с сервера, отказ — `api_require`).
   Заказанная нота (пакет, год имени) стоит на экране БЛОКОМ, пока ждёт оплаты
   (05.11): её отдаёт сервер вместе со счётом (`account.notes`), а не память
   экрана; «Plătește cu cardul» ведёт на страницу оплаты DentPilot в браузере
   Windows — обычной ссылкой, как «Plătește acum» (ничего одноразового).
   ⛔ Тексты клиника НЕ правит: выбирает готовый вариант и видит предпросмотр
   со своим названием; число сегментов считает сервер. Каждое изменение
   сохраняется сразу — ответ приносит свежие данные и предпросмотры. */
const T = {
  title: 'SMS pentru pacienți',
  sub: 'memento-uri despre vizita programată, trimise în numele clinicii',
  offline: 'Programul nu răspunde. Reîncercați.',
  unavailable: 'Memento-urile SMS sunt disponibile doar în programul activat cu licență.',
  notOffered: 'Modulul SMS nu este disponibil acum pentru clinica dvs.',
  offBasic: 'Modulul SMS este oprit: el face parte din DentPilot Plus.',
  toPlus: 'Îl porniți plătind varianta Plus în Setări › Licența („Plătește acum”) sau scriindu-ne:',
  offManual: 'Modulul SMS este oprit.',
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
  recallTitle: 'Rechemări',
  recall: 'Buton „SMS” în lista Rechemări',
  recallHint: 'recepția trimite, la apăsare, o singură reamintire a controlului periodic pentru fiecare termen; '
    + 'textul conține doar denumirea și telefonul clinicii',
  recallNoPhone: 'butonul apare după ce completați telefonul clinicii în Setări › Clinica',
  recallAuto: 'Trimite SMS automat când pacientul ajunge în listă',
  recallAutoHint: 'programul trimite singur, între 08:00 și 21:00, cel mult {n} SMS pe zi — cei mai întârziați primii; '
    + 'restul rămân pentru butonul SMS și pentru telefon. La început este oprită: la o clinică cu istoric lung ar pleca zeci de SMS în prima zi.',
  previewRo: 'română',
  previewRu: 'русский',
  segments1: '1 SMS',
  segmentsN: '{n} SMS pe memento',
  /* Честно о числе SMS (w2-look § 1): русский с «Anulare» и «Detaliat» — уже два */
  previewHint: 'Textele sunt stabilite de DentPilot, fără date despre tratament. Standard, Scurt, Oficial și Cald '
    + 'încap într-un SMS în română; în rusă — un SMS fără rândul „Anulare”, 2 SMS cu el. Detaliat și textul cu '
    + 'link — 2 SMS. Câte SMS costă fiecare text scrie deasupra lui. Limba — din fișa pacientului. Text propriu — '
    + 'la cerere, scrieți-ne.',
  variantParts: '{label} ({n} SMS)',
  // ответ пациента ссылкой (Premium, волна 2а; раскладка A — сразу под «Cu o zi înainte»)
  link: 'Pacientul răspunde prin link (Vin / Nu pot veni)',
  premium: 'Premium',
  linkHint: 'În memento apare un link scurt. Pacientul apasă „Vin” sau „Nu pot veni”, iar răspunsul se vede '
    + 'în fereastra vizitei: „Confirmat · SMS” sau „Nu poate veni · SMS”. Programul nu anulează nimic '
    + 'singur — recepția sună pacientul.',
  linkWarn: 'Atenție: SMS-ul cu link este întotdeauna lung — {n} SMS din pachet pentru fiecare memento '
    + '„Cu o zi înainte” (în loc de 1).',
  linkLocked: 'cu link — textul {variant}',
  plusOff: 'Disponibil în Premium',
  plusHint: 'Pacientul confirmă sau anunță că nu poate veni dintr-un link din SMS, fără să sune la clinică.',
  notify: 'Anunță pe ecran răspunsurile pacienților',
  notifyHint: 'Plăcuță jos în dreapta, pentru recepție și director (medicul — doar pentru pacienții lui): '
    + '„Vin” dispare singură, „Nu poate veni” rămâne până o închideți. Răspunsurile din timpul nopții nu '
    + 'apar dimineața ca plăcuțe — sunt în fereastra vizitei.',
  // подарки Premium в «Starea pachetului» (облако: `gifts`, `name_year: free`)
  giftSms: '{n} SMS incluse la prima plată Premium',
  giftSmsDay: 'adăugate pe {day}',
  giftName: 'Numele expeditorului (până la 11 caractere) inclus (Premium anual)',
  giftNameWho: '{name}, fără plata anului numelui',
  senderFree: 'inclus în Premium anual',
  forecastTitle: 'Consum estimat',
  forecast: '~{month} SMS pe lună ({visits} vizite cu telefon în ultimele 30 de zile)',
  forecastLeft: ' · restul ajunge pentru ~{days}',
  // число дней — румынской формой (09.11: было «~1 zile»): 1 zi, 2–19 zile, 20 de zile
  days1: '{n} zi',
  daysFew: '{n} zile',
  daysMany: '{n} de zile',
  forecastNone: 'Încă nu sunt vizite pentru estimare.',
  // разбивка по событиям: SMS на визит у каждого напоминания (`forecast.parts`)
  forecastEv: '{event} — {visits} × {n} SMS = {sum}',
  forecastOff: '{event} — oprit',
  forecastLink: 'textul cu link',
  orderTitle: 'Comandă',
  orderHint: 'Nota de plată o plătiți cu cardul sau prin transfer bancar; după plată SMS-urile se adaugă automat.',
  packBtn: '{units} SMS — {price} MDL',
  packConfirm: 'Comandați {units} SMS pentru {price} MDL? Primiți nota de plată: o plătiți cu cardul, '
    + 'pe pagina de plată, sau prin transfer bancar. Nota vine și pe e-mail.',
  packNone: 'Pachetele nu sunt încă disponibile.',
  // Ожидающая нота: способы оплаты картой — фразой условий § 4.3, той же, что на странице оплаты и
  // в письме (cloud mail.CARD_WAYS / CARD_SAFE; согласие держит cloud/tests/test_sms_cabinet.py)
  note: 'Nota de plată {ref}',
  notePack: 'pachet {units} SMS',
  noteName: 'numele de expeditor, un an',
  noteWaiting: 'în așteptare',
  notePay: 'Plătește cu cardul',
  notePayHint: 'Plata cu cardul se face pe pagina securizată a băncii maib: card Visa sau Mastercard, '
    + 'Google Pay sau Apple Pay. Datele cardului nu ajung la DentPilot.',
  noteTransfer: 'Prin transfer bancar: datele și referința sunt în e-mailul cu nota de plată.',
  noteTransferOr: 'Sau prin transfer bancar: datele și referința sunt în e-mailul cu nota de plată.',
  noteAfterPack: 'După confirmarea plății SMS-urile se adaugă automat.',
  noteAfterName: 'După confirmarea plății anul numelui se înregistrează automat.',
  senderTitle: 'Numele expeditorului',
  senderNone: 'SMS-urile pleacă de la numele „DentPilot" cu denumirea clinicii în text. Puteți cere numele propriu (până la 11 caractere latine).',
  senderRequested: 'cerere trimisă — descărcați cererea completată în contul clinicii (cloud.dentpilot.md/cont), semnați-o și încărcați-o acolo',
  senderSubmitted: 'la operatori: 1–2 zile lucrătoare',
  senderActive: 'activ',
  senderRejected: 'respins',
  senderUntil: 'plătit până la {date}',
  senderPh: 'Numele (ex. ZambetDent)',
  senderBtn: 'Cere numele',
  senderRule: 'Maximum {max} caractere: litere latine, cifre, spațiu, punct sau cratimă.',
  senderBadChar: 'Caracterul „{ch}” nu este permis: doar litere latine fără diacritice, cifre, spațiu, punct sau cratimă.',
  senderNoLetter: 'Numele trebuie să conțină cel puțin o literă.',
  senderNameBtn: 'Comandă numele — {price} MDL / an',
  senderNameConfirm: 'Comandați numele propriu de expeditor pentru un an ({price} MDL)? Primiți nota de plată: '
    + 'o plătiți cu cardul, pe pagina de plată, sau prin transfer bancar. Nota vine și pe e-mail.',
  testTitle: 'SMS de test',
  testHint: 'Pe numărul dvs. mobil, din pachetul clinicii.',
  testPh: 'Telefon mobil',
  testBtn: 'Trimite',
  directorOnly: 'Comanda și testul — doar directorul.',
} as const

const SENDER: Record<string, string> = {
  requested: T.senderRequested, submitted: T.senderSubmitted, active: T.senderActive, rejected: T.senderRejected,
}

/* Правило имени отправителя — двойник `SENDER_RE` сервера лицензий: поле показывает его до заявки,
   решает по-прежнему сервер. Поле режет лишнее само, поэтому предел назван словами рядом. */
const SENDER_MAX = 11
const SENDER_BAD = /[^A-Za-z0-9 .-]/

function senderProblem(name: string): string {
  const bad = SENDER_BAD.exec(name)
  if (bad) return T.senderBadChar.replace('{ch}', bad[0])
  if (name.trim() && !/[A-Za-z]/.test(name)) return T.senderNoLetter
  return ''
}

/* Модуль выключен в облаке — не ошибка, а состояние с путём назад (23.10):
   тариф Basic ведёт к оплате Plus, тумблер облака — к нам. Причины кодов —
   `sms_loop.WHY`; код, которого здесь нет, остаётся красной строкой `why`. */
const CALM: Record<string, { head: string; path: string }> = {
  sms_basic: { head: T.offBasic, path: T.toPlus },
  sms_off: { head: T.offManual, path: T.resume },
}

interface Props {
  navigate?: (url: string) => void
}

/** Подпись варианта в списке: дороже одной SMS — числом рядом («Detaliat (2 SMS)»). */
function variantLabel(v: SmsVariant): string {
  return v.parts && v.parts > 1 ? T.variantParts.replace('{label}', v.label).replace('{n}', String(v.parts)) : v.label
}

/** Правка ответа пациента ссылкой: ключ `link` шлётся целиком, как остальные настройки. */
function withLink(f: SmsSettingsForm, patch: Partial<{ confirm: boolean; notify: boolean }>): SmsSettingsForm {
  return { ...f, link: { confirm: false, notify: true, ...f.link, ...patch } }
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

  /* Ответ заказа несёт свежие данные экрана (`screen`): нота уже в счёте сервера. */
  function ordered(r: ApiResult<SmsOrder>) {
    setOrder(r.data)
    if (r.data.screen) replace(r.data.screen)
  }

  async function orderPack(units: number, price: number) {
    const text = T.packConfirm.replace('{units}', String(units)).replace('{price}', String(price))
    if (!await ask({ text, ok: T.orderTitle })) return
    void run(() => settings.smsOrder(units), ordered)
  }

  async function orderName(price: number) {
    if (!await ask({ text: T.senderNameConfirm.replace('{price}', String(price)), ok: T.orderTitle })) return
    void run(() => settings.smsOrderName(), ordered)
  }

  function requestSender(e: FormEvent) {
    e.preventDefault()
    if (!sender.trim() || senderProblem(sender)) return
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
  /* Ожидающие ноты: список сервера — блок стоит, пока нота ждёт оплаты, и уходит сам. Сервер их
     не шлёт (до 05.11: `notes` нет) — как раньше, только нота последнего заказа, до ухода с экрана. */
  const notes: SmsNote[] = acc?.notes ?? (order ? [order] : [])
  const calm: { head: string; path: string } | undefined =
    data && data.offered && Object.hasOwn(CALM, data.blocked) ? CALM[data.blocked] : undefined
  const senderBad = senderProblem(sender)
  const gifts = acc?.gifts ?? null
  const giftSms = Boolean(gifts && gifts.bonus_units > 0 && gifts.bonus_day)
  /* имя в Premium: облако говорит состоянием года (`free`) и сроком в подарках — любое из двух */
  const nameFree = acc?.name_year === 'free' || Boolean(gifts?.name_free)
  const link = data?.link
  const lf = s?.link
  const seg = (n: number) => (n <= 1 ? T.segments1 : T.segmentsN.replace('{n}', String(n)))
  /* Текст со ссылкой — свой предпросмотр сервера (`previews.link`, адрес-образец): выбранный вариант
     при включённой ссылке не действует */
  const linkOn = Boolean(data?.link?.on)
  const preview = (event: string, variant: string) => {
    const p: Record<string, SmsPreview> | undefined = linkOn && event === data?.link?.event
      ? (data.previews.link as unknown as Record<string, SmsPreview> | undefined)
      : data?.previews[event]?.[variant]
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
      {data && calm && (
        <div className="banner warn" role="status">
          <b>{calm.head}</b> {calm.path} {data.support.phone} · {data.support.email}
        </div>
      )}
      {data && data.offered && !data.enabled && data.why && !calm && (
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
            {T.lastAt}: {data.last.when || '—'}
            {data.last.error_text ? ` · ${data.last.error_text}` : ''}
            {' '}
            <button type="button" className="dp-link" disabled={busy}
              onClick={() => void run(() => settings.smsRefresh(), (r) => replace(r.data))}>
              <Icon name="refresh" /> {T.check}
            </button>
          </p>
          {(giftSms || nameFree) && (
            <div className="dp-sms-incl">
              {giftSms && (
                <div><Icon name="check" /><span><b>{T.giftSms.replace('{n}', String(gifts?.bonus_units))}</b>
                  {' '}<small>· {T.giftSmsDay.replace('{day}', gifts?.bonus_day ?? '')}</small></span></div>
              )}
              {nameFree && (
                <div><Icon name="check" /><span><b>{T.giftName}</b>
                  {acc.sender ? <>{' '}<small>· {T.giftNameWho.replace('{name}', acc.sender)}</small></> : null}</span></div>
              )}
            </div>
          )}
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
              {/* со ссылкой текст всегда длинный — выбор заперт на варианте сервера (`link.variant`) */}
              <select value={linkOn && link ? link.variant : s.day_before.variant} disabled={busy || linkOn}
                aria-label={T.dayBefore + ' — textul'}
                onChange={(e) => save((f) => ({ ...f, day_before: { ...f.day_before, variant: e.target.value } }))}>
                {data.options.variants.map((v) => <option key={v.key} value={v.key}>{variantLabel(v)}</option>)}
              </select>
              {linkOn && link && (
                <span className="dp-sms-lockv">
                  {T.linkLocked.replace('{variant}',
                    data.options.variants.find((v) => v.key === link.variant)?.label ?? link.variant)}
                </span>
              )}
            </div>
            {link && lf && (link.allowed ? (
              <div className="dp-sms-link">
                <label>
                  <input type="checkbox" checked={lf.confirm} disabled={busy}
                    onChange={(e) => save((f) => withLink(f, { confirm: e.target.checked }))} />
                  {' '}<b>{T.link}</b> <span className="dp-sms-tag">{T.premium}</span>
                </label>
                <p className="hint">{T.linkHint}</p>
                <div className="dp-sms-warn"><Icon name="excl" /><span>{T.linkWarn.replace('{n}', String(link.parts))}</span></div>
                <div className={`dp-sms-sub${lf.confirm ? '' : ' off'}`}>
                  <label>
                    <input type="checkbox" checked={lf.confirm && lf.notify} disabled={busy || !lf.confirm}
                      onChange={(e) => save((f) => withLink(f, { notify: e.target.checked }))} />
                    {' '}{T.notify}
                  </label>
                  {lf.confirm && <p className="hint">{T.notifyHint}</p>}
                </div>
              </div>
            ) : (
              /* Basic/Plus: на месте галочки — «Disponibil în Premium» (Олег 27.11) */
              <div className="dp-sms-link off">
                <label>
                  <input type="checkbox" checked={false} disabled />
                  {' '}{T.link} <span className="chip mute"><Icon name="lock" /> {T.plusOff}</span>
                </label>
                <p className="hint">{T.plusHint}</p>
                <div className="dp-sms-sub off">
                  <label><input type="checkbox" checked={false} disabled /> {T.notify}</label>
                </div>
              </div>
            ))}
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
                {data.options.variants.map((v) => <option key={v.key} value={v.key}>{variantLabel(v)}</option>)}
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

          {/* «Rechemări» (30.10): кнопка SMS в списке — галочка (по умолчанию
              включена, Олег 30.10) и вариант текста; предпросмотр тем же путём */}
          <h3>{T.recallTitle}</h3>
          <div className="dp-sms-events">
            <div className="dp-sms-ev">
              <label>
                <input type="checkbox" checked={s.recall.on} disabled={busy}
                  onChange={(e) => save((f) => ({ ...f, recall: { ...f.recall, on: e.target.checked } }))} />
                {' '}<b>{T.recall}</b>
              </label>
              <span className="dp-muted">{T.variant}</span>
              <select value={s.recall.variant} disabled={busy} aria-label={T.recall + ' — textul'}
                onChange={(e) => save((f) => ({ ...f, recall: { ...f.recall, variant: e.target.value } }))}>
                {data.options.recall_variants.map((v) => <option key={v.key} value={v.key}>{v.label}</option>)}
              </select>
            </div>
            <p className="hint">{data.clinic.phone ? T.recallHint : T.recallNoPhone}</p>
            {/* автоматическая отправка (Олег 30.10 утром, В1 → В): выключена по
                умолчанию; действует только вместе с кнопкой — без неё серая */}
            <div className="dp-sms-ev">
              <label>
                <input type="checkbox" checked={s.recall.on && s.recall.auto} disabled={busy || !s.recall.on}
                  onChange={(e) => save((f) => ({ ...f, recall: { ...f.recall, auto: e.target.checked } }))} />
                {' '}{T.recallAuto}
              </label>
            </div>
            <p className="hint">{T.recallAutoHint.replace('{n}', String(data.options.recall_auto_daily))}</p>
            {s.recall.on && preview('recall', s.recall.variant)}
          </div>

          <h3>{T.forecastTitle}</h3>
          <p className="hint">
            {data.forecast.visits > 0
              ? T.forecast.replace('{month}', String(data.forecast.month)).replace('{visits}', String(data.forecast.visits))
                + (data.forecast.days_left !== null && acc ? T.forecastLeft.replace('{days}', roCount(data.forecast.days_left,
                  { one: T.days1, few: T.daysFew, many: T.daysMany })) : '')
              : T.forecastNone}
          </p>
          {data.forecast.visits > 0 && data.forecast.parts && (
            <ul className="dp-sms-fc">
              {([['day_before', T.dayBefore], ['same_day', T.sameDay]] as const).map(([ev, name]) => {
                const n = data.forecast.parts?.[ev] ?? 0
                const v = data.forecast.visits
                if (!n) return <li key={ev}>{T.forecastOff.replace('{event}', name)}</li>
                const chosen = ev === 'day_before' ? s.day_before.variant : s.same_day.variant
                const why = linkOn && ev === link?.event ? T.forecastLink
                  : data.options.variants.find((x) => x.key === chosen)?.label ?? ''
                return (
                  <li key={ev}>
                    {T.forecastEv.replace('{event}', name).replace('{visits}', String(v)).replace('{n}', String(n))
                      .replace('{sum}', String(v * n))}{why ? ` (${why})` : ''}
                  </li>
                )
              })}
            </ul>
          )}
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
              {acc.sender_until && !nameFree ? ` · ${T.senderUntil.replace('{date}', acc.sender_until.slice(0, 10))}` : ''}
              {nameFree ? ` · ${T.senderFree}` : ''}
            </p>
          )}
          {data.can_order ? (
            <>
              {(acc.sender_state === 'none' || acc.sender_state === 'rejected') && (
                <form className="add dp-sms-name" onSubmit={requestSender}>
                  <input value={sender} placeholder={T.senderPh} aria-label={T.senderPh} maxLength={SENDER_MAX} required
                    style={{ width: 220 }} disabled={busy} aria-invalid={senderBad ? true : undefined}
                    aria-describedby="dp-sms-name-rule"
                    onChange={(e) => setSender(e.target.value.slice(0, SENDER_MAX))} />
                  <button disabled={busy || !sender.trim() || senderBad !== ''}>{T.senderBtn}</button>
                  <small id="dp-sms-name-rule" className="dp-sms-rule">
                    {T.senderRule.replace('{max}', String(SENDER_MAX))}
                    {sender ? ` ${sender.length} / ${SENDER_MAX}` : ''}
                  </small>
                  {senderBad && <small className="dp-sms-rule bad" role="alert">{senderBad}</small>}
                </form>
              )}
              {/* имя в Premium на год оплаты не просит: облако ответило бы `sms_name_free` */}
              {acc.sender_state !== 'none' && acc.name_price > 0 && !nameFree && (
                <p className="dp-actions">
                  <button type="button" className="savebtn" disabled={busy} onClick={() => void orderName(acc.name_price)}>
                    <Icon name="card" /> {T.senderNameBtn.replace('{price}', String(acc.name_price))}
                  </button>
                </p>
              )}

              <h3>{T.orderTitle}</h3>
              <p className="hint">{T.orderHint}</p>
              {acc.packs.length ? (
                <p className="dp-actions dp-sms-packs">
                  {acc.packs.map((p) => (
                    <button key={p.units} type="button" className="savebtn" disabled={busy}
                      onClick={() => void orderPack(p.units, p.price)}>
                      <Icon name="cash" /> {T.packBtn.replace('{units}', String(p.units)).replace('{price}', String(p.price))}
                    </button>
                  ))}
                </p>
              ) : <p className="hint">{T.packNone}</p>}
              {notes.map((n) => (
                <div key={n.reference}>
                  <div className="banner warn" role="status">
                    <b>{T.note.replace('{ref}', n.reference)}</b>
                    {' — '}{n.kind === 'sms_name' ? T.noteName : T.notePack.replace('{units}', String(n.units ?? ''))}
                    {': '}<b>{n.amount} MDL</b>{' · '}{T.noteWaiting}
                  </div>
                  {/* страница оплаты — чужой адрес: AppLink отдаёт обычную ссылку, target=_blank
                      уводит её в системный браузер, как «Plătește acum»; адрес проверил движок */}
                  {n.pay_url ? (
                    <>
                      <p className="dp-actions">
                        <AppLink className="pl-btn primary" href={n.pay_url} target="_blank" rel="noopener">
                          <Icon name="card" /> {T.notePay}
                        </AppLink>
                      </p>
                      <p className="hint">{T.notePayHint}</p>
                    </>
                  ) : null}
                  <p className="hint">
                    {n.pay_url ? T.noteTransferOr : T.noteTransfer}{' '}
                    {n.kind === 'sms_name' ? T.noteAfterName : T.noteAfterPack}
                  </p>
                </div>
              ))}

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
