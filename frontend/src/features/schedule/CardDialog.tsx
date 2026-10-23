import { useEffect, useRef, useState, type FormEvent } from 'react'
import { AppLink } from '../../components/AppLink'
import { when } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import { day, type ServiceOption, type StatusAction, type VisitCardView } from './day'
import { CALL_WORDS, type CallResult } from './desk'

/* Карточка визита по клику (C25.5b): что это за визит, комментарий стойки и
   кнопки исхода.

   Раскладка «три этажа» (23.10, выбор Олега по кадрам `design/visit-card`,
   вариант A с рядом 1 — «много кнопок и разные цвета»): факты → связь →
   работа, и один фирменный акцент на окно.
   - факты: услуга с карандашом смены процедуры, врач; телефон и возраст
     второй строкой. Карандаш раскрывает список и контурную «Schimbă» —
     большой кнопки у редкого действия больше нет;
   - связь: фиша и дневник — контурные чипы в одну строку; звонок —
     сегмент [Confirmat | Nu răspunde]: горит отмеченный, повторный щелчок по
     горящему снимает отметку (прежняя «Anulează bifa»; в меню правой кнопки
     она остаётся пунктом);
   - работа: поле комментария; кнопка сохранения появляется ТОЛЬКО когда
     текст тронут, сохранение закрывает окно (14.10, слово Олега);
   - исходы (ряд 1): первая ступень матрицы — большая фирменная кнопка,
     остальные ступени — контуром справа, «Nu a venit» и «Anulează» — тихой
     строкой под рядом; у закрытого визита — «Redeschide» контуром.
   Цвета смысла у исходов сняты: три из пяти кнопок — ступени одного
   конвейера, и фирменный акцент говорит «что обычно дальше». «Lista zilei» и
   экран у кресла (`.act`, `.bstat`) не тронуты.

   ⛔ Комментарий правится ПОЛНЫЙ — тот, что приехал в `cards`. В карточке
   сетки он обрезан до 60 знаков, и сохранение обрезанного укоротило бы текст
   без единой правки (прайор 08-16: пересохранение обязано быть
   тождественным).
   ⛔ Набор кнопок приходит С СЕРВЕРА (`actions[st]`) — той же матрицей, что
   печатает список дня. Свой список в браузере разошёлся бы молча: закрытая
   запись потеряла бы возврат в одном месте и сохранила в другом. Окно делит
   его на ступени и исключения ПО КЛАССУ кнопки (`b-noshow`, `b-cancel`,
   `b-reopen` — исключения, всё прочее — ступени в порядке сервера): состав и
   порядок — серверные, здесь только вес и место.
   ⚠️ Другая запись — другой диалог: экран пересоздаёт его по номеру визита,
   поэтому в поле всегда комментарий ТОЙ записи, которую открыли.
   ⭐ Принимает УЗКИЙ вид `VisitCardView` (C26.5.3-a), а не модель дня: под
   него ложатся и карточка дня, и блок канвы панели, и диалог у двух экранов
   остаётся ОДИН. Заведи второй — и на одном экране у визита появится ссылка
   на фишу, а на другом нет; увидеть это можно, только открыв оба. */
const T = {
  fisa: 'Fișa pacientului',
  visitNew: 'Completează consultația',
  visitOld: 'Consultația',
  comment: 'Comentariu: alergii, preferințe, de sunat înapoi…',
  save: 'Salvează comentariul',
  svc: 'Procedura',
  svcChange: 'Schimbă procedura',
  svcSave: 'Schimbă',
  svcCancel: 'Renunță',
  close: 'Închide',
} as const

/** Исключения ряда исходов — по классу кнопки сервера; всё остальное — ступени. */
const NEG_CLS = ['b-noshow', 'b-cancel']
export function splitActions(actions: StatusAction[]): {
  steps: StatusAction[]; neg: StatusAction[]; reopen: StatusAction | null
} {
  return {
    steps: actions.filter((a) => !NEG_CLS.includes(a.cls) && a.cls !== 'b-reopen'),
    neg: actions.filter((a) => NEG_CLS.includes(a.cls)),
    reopen: actions.find((a) => a.cls === 'b-reopen') ?? null,
  }
}

interface Props {
  open: boolean
  id: number
  card: VisitCardView
  actions: StatusAction[]
  /** Плашка над карточкой: непусто — запись исчезла, действовать не над чем
   *  (надгробие, C26.5.3-b). Кнопок в этом случае не приходит вовсе. */
  note?: string
  /** Адрес возврата для дневника визита — та же страница того же дня. */
  back: string
  busy: boolean
  onClose: () => void
  /** `true` — сохранено, окно закрывается; `false` — отказ, набранное остаётся. */
  onComment: (text: string) => Promise<boolean>
  onStatus: (to: string) => Promise<boolean>
  /** Отметка звонка-подтверждения (12.10, слово Олега: «вчера не позвонил —
   *  хочу подтвердить сегодня»). Сегмент виден, только когда сервер сказал
   *  `callable`; диалог остаётся открытым — отметка приезжает с каналом. */
  onCall?: (result: CallResult) => Promise<boolean>
  /** Смена процедуры (22.10, Олег: только смена, вторая услуга — нет).
   *  Список услуг окно спрашивает само (`day.serviceOptions`), когда сервер
   *  сказал `service_edit`: в блоке живого канала списка нет.
   *  `true` — сменено, окно закрывается; отказ приходит словом в `fail` и
   *  печатается В ОКНЕ: плашка экрана под `<dialog>` не видна. */
  onService?: (serviceId: string, fail: (text: string) => void) => Promise<boolean>
}

export function CardDialog({ open, id, card, actions, note = '', back, busy,
  onClose, onComment, onStatus, onCall, onService }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  /* Черновик и то, чем его засеяли, — ОДНИМ состоянием: «тронут ли» решается
     сравнением этих двух, и оба нужны на рендере (кнопка сохранения), где
     ref читать нельзя. */
  const [cmt, setCmt] = useState({ text: card.comment, seeded: card.comment })
  const text = cmt.text
  const dirty = cmt.text !== cmt.seeded
  /* Выбор процедуры живёт тем же правилом, что черновик комментария: пока
     его не трогали, приехавшая со второго рабочего места смена пересевает
     список; тронули — выбор остаётся. Список раскрывает карандаш (23.10):
     закрытый список — это нетронутый выбор. */
  const [svc, setSvc] = useState(card.service_id)
  const svcSeeded = useRef(card.service_id)
  const [svcOpen, setSvcOpen] = useState(false)
  const [svcFail, setSvcFail] = useState('')
  /* Список услуг врача этого визита — ответ сервера; `null` — ещё не пришёл
     (или не спрашивали), карандаша на экране нет. */
  const [svcOpts, setSvcOpts] = useState<ServiceOption[] | null>(null)
  const svcAsk = !!onService && !note && card.service_edit
  /* ⭐ Черновик держит СЕБЯ, а не экран (C26.5.3-b). Пока его не трогали —
     приехавшее значение пересевает поле, и правка со второго рабочего места
     видна сразу. Тронули — поле остаётся, а канва под диалогом продолжает
     жить: старый `panel.js` на любом открытом окне замораживал страницу
     целиком, и рабочее место с забытой карточкой переставало узнавать о
     бронях, оставаясь живым НА ВИД.
     ⚠️ Чистоту решает сравнение с тем, ЧЕМ ЗАСЕЯЛИ, а не с текущим значением
     карточки: иначе текст, случайно набранный слово в слово, считался бы
     грязным навсегда. По той же чистоте решается, показывать ли кнопку
     сохранения (23.10): нетронутому полю сохранять нечего. */

  useEffect(() => {
    if (open) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [open])

  /* Пересев — НА РЕНДЕРЕ по смене пришедшего значения (приём React «состояние
     от прошлого рендера»), а не эффектом: эффект сработал бы кадром позже, и
     кнопка сохранения на этот кадр показалась бы у нетронутого поля. */
  if (cmt.seeded !== card.comment && !dirty) {
    setCmt({ text: card.comment, seeded: card.comment })
  }

  /* Спросить список при открытии — один раз на окно (другой визит — другое
     окно, экран пересоздаёт его по номеру). Отказ сети — карандаша нет, а
     остальное окно живёт как жило. */
  useEffect(() => {
    if (!svcAsk) return
    const ctl = new AbortController()
    day.serviceOptions(id, ctl.signal).then(
      (r) => { if (!ctl.signal.aborted) setSvcOpts(r.data.options) },
      () => { if (!ctl.signal.aborted) setSvcOpts([]) },
    )
    return () => ctl.abort()
  }, [svcAsk, id])

  useEffect(() => {
    setSvc((cur) => {
      if (cur !== svcSeeded.current) return cur
      svcSeeded.current = card.service_id
      return card.service_id
    })
  }, [card.service_id])

  /* ⛔ «Можно ли» и список решает СЕРВЕР: у закрытого визита, у врача в
     отпуске и у легаси-строки `service_edit` снят, и окно не спрашивает
     вовсе. Своего правила браузер не считает. */
  const svcList = svcAsk ? svcOpts ?? [] : []
  const svcShown = svcList.length > 0
  /* Нынешней услуги в списке может не быть (легаси-строка без ключа, услугу
     убрали из clinic.json): тогда она стоит первой строкой, выбрать её нельзя. */
  const svcKnown = svcList.some((s) => s.id === card.service_id)

  async function saveSvc(e: FormEvent) {
    e.preventDefault()
    if (!onService) return
    setSvcFail('')
    if (await onService(svc, setSvcFail)) onClose()
  }

  function closeSvc() {
    setSvcOpen(false)
    setSvcFail('')
    setSvc(card.service_id)
    svcSeeded.current = card.service_id
  }

  /* Сохранённый комментарий закрывает окно, как исход визита (14.10, слово
     Олега: «вкладка по идее должна закрыться»); отказ оставляет окно с
     набранным. Отметка звонка окно держит — она часто идёт перед исходом. */
  async function save(e: FormEvent) {
    e.preventDefault()
    if (await onComment(text)) onClose()
  }

  const { steps, neg, reopen } = splitActions(actions)
  const [next, ...rest] = steps
  const run = (a: StatusAction) => { void when(a.confirm, () => { void onStatus(a.to) }) }

  return (
    <dialog ref={ref} onClose={onClose}>
      <div className="dlg-head">
        <span>{card.time} — {card.name}</span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <div className="dlg-form">
        {/* Надгробие: запись исчезла, пока диалог открыт. Слово взято у
            легаси (`MSG_BANNER["mv_gone"]`), а не придумано. */}
        {note && <div className="banner err" role="alert">{note}</div>}
        <div className="dp-card-facts">
          <div className="dp-card-fl">
            <span className="dp-card-w">
              {card.service}
              {svcShown && !svcOpen && (
                <button type="button" className="dp-card-pen" disabled={busy}
                  title={T.svcChange} aria-label={T.svcChange}
                  onClick={() => setSvcOpen(true)}><Icon name="pen" /></button>
              )}
            </span>
            {card.doctor ? <span className="dp-card-w"><span className="dp-card-dot">·</span>{card.doctor}</span> : null}
          </div>
          {(card.phone || card.age) ? (
            <div className="dp-card-fl dp-card-sub">
              {card.phone ? <span>{card.phone}</span> : null}
              {card.age ? (
                <span className="dp-card-w">
                  {card.phone ? <span className="dp-card-dot">·</span> : null}{card.age} ani
                </span>
              ) : null}
            </div>
          ) : null}
          {svcShown && svcOpen && (
            <form onSubmit={saveSvc} className="dp-card-svc" aria-label={T.svc}>
              {svcFail ? <div className="banner err" role="alert">{svcFail}</div> : null}
              <select value={svc} aria-label={T.svc} autoFocus
                      onChange={(e) => { setSvc(e.target.value); setSvcFail('') }}>
                {svcKnown ? null : <option value={card.service_id} disabled>{card.service}</option>}
                {svcList.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
              </select>
              <button className="dp-card-chip strong" disabled={busy || svc === card.service_id}>
                <Icon name="pen" /> {T.svcSave}
              </button>
              <button type="button" className="dp-card-quiet" onClick={closeSvc}>{T.svcCancel}</button>
            </form>
          )}
        </div>
        {card.pid ? (
          <div className="dp-card-links">
            <AppLink className="dp-card-link dp-card-chip" href={`/admin/patient/${card.pid}`}>
              <Icon name="id" /> {T.fisa}
            </AppLink>
            <AppLink className="dp-card-link dp-card-chip"
               href={`/admin/visit/${id}?back=${encodeURIComponent(back)}`}>
              <Icon name="med" /> {card.rec ? T.visitOld : T.visitNew}
            </AppLink>
          </div>
        ) : null}
        {card.callable && onCall && !note && (
          <div className="dp-card-call" role="group" aria-label={CALL_WORDS.call}>
            <span className="dp-card-call-l"><Icon name="phone" /> {CALL_WORDS.call}</span>
            <span className="dp-card-seg">
              <button type="button" className={`dp-card-seg-b ok${card.call === 'ok' ? ' on' : ''}`}
                aria-pressed={card.call === 'ok'} disabled={busy}
                title={card.call === 'ok' ? CALL_WORDS.undo : CALL_WORDS.ok}
                onClick={() => { void onCall(card.call === 'ok' ? '' : 'ok') }}>
                <Icon name="check" /> {CALL_WORDS.ok}
              </button>
              <button type="button" className={`dp-card-seg-b no${card.call === 'noanswer' ? ' on' : ''}`}
                aria-pressed={card.call === 'noanswer'} disabled={busy}
                title={card.call === 'noanswer' ? CALL_WORDS.undo : CALL_WORDS.no}
                onClick={() => { void onCall(card.call === 'noanswer' ? '' : 'noanswer') }}>
                <Icon name="phone-off" /> {CALL_WORDS.no}
              </button>
            </span>
          </div>
        )}
        <form onSubmit={save} className="dp-card-cmt">
          <textarea value={text} rows={2} maxLength={300} placeholder={T.comment}
                    onChange={(e) => setCmt((c) => ({ ...c, text: e.target.value }))} />
          {dirty && (
            <div className="dp-card-cmt-b">
              <button className="dp-card-chip strong" disabled={busy}><Icon name="chat" /> {T.save}</button>
            </div>
          )}
        </form>
      </div>
      {(next || reopen) && (
        <div className="dlg-status dp-card-foot">
          {next && (
            <button type="button" className="dp-card-next" disabled={busy} onClick={() => run(next)}>
              {next.label}
            </button>
          )}
          {rest.map((a) => (
            <button key={a.to} type="button" className="dp-card-step" disabled={busy} onClick={() => run(a)}>
              {a.label}
            </button>
          ))}
          {reopen && (
            <button type="button" className="dp-card-step reopen" disabled={busy} onClick={() => run(reopen)}>
              <Icon name="undo" /> {reopen.label}
            </button>
          )}
        </div>
      )}
      {neg.length > 0 && (
        <div className="dp-card-neg">
          {neg.map((a) => (
            <button key={a.to} type="button" className={`dp-card-quiet ${a.cls}`} disabled={busy}
              onClick={() => run(a)}>{a.label}</button>
          ))}
        </div>
      )}
    </dialog>
  )
}
