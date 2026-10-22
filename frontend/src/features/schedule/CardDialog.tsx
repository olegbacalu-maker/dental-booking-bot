import { useEffect, useRef, useState, type FormEvent } from 'react'
import { AppLink } from '../../components/AppLink'
import { when } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import { day, type ServiceOption, type StatusAction, type VisitCardView } from './day'
import { CALL_WORDS, type CallResult } from './desk'

/* Карточка визита по клику (C25.5b): что это за визит, комментарий стойки и
   кнопки исхода.

   ⛔ Комментарий правится ПОЛНЫЙ — тот, что приехал в `cards`. В карточке
   сетки он обрезан до 60 знаков, и сохранение обрезанного укоротило бы текст
   без единой правки (прайор 08-16: пересохранение обязано быть
   тождественным).
   ⛔ Набор кнопок приходит С СЕРВЕРА (`actions[st]`) — той же матрицей, что
   печатает список дня. Свой список в браузере разошёлся бы молча: закрытая
   запись потеряла бы возврат в одном месте и сохранила в другом.
   ⚠️ Другая запись — другой диалог: экран пересоздаёт его по номеру визита,
   поэтому в поле всегда комментарий ТОЙ записи, которую открыли.
   ⭐ Принимает УЗКИЙ вид `VisitCardView` (C26.5.3-a), а не модель дня: под
   него ложатся и карточка дня, и блок канвы панели, и диалог у двух экранов
   остаётся ОДИН. Заведи второй — и на одном экране у визита появится ссылка
   на фишу, а на другом нет; увидеть это можно, только открыв оба. */
const T = {
  fisa: 'Deschide fișa pacientului ›',
  visitNew: 'Completează consultația ›',
  visitOld: 'Vezi consultația ›',
  comment: 'Comentariu: alergii, preferințe, de sunat înapoi…',
  save: 'Salvează comentariul',
  svc: 'Procedura',
  svcSave: 'Schimbă procedura',
  close: 'Închide',
} as const

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
   *  хочу подтвердить сегодня»). Строка видна, только когда сервер сказал
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
  const [text, setText] = useState(card.comment)
  /* Выбор процедуры живёт тем же правилом, что черновик комментария: пока
     его не трогали, приехавшая со второго рабочего места смена пересевает
     список; тронули — выбор остаётся. */
  const [svc, setSvc] = useState(card.service_id)
  const svcSeeded = useRef(card.service_id)
  const [svcFail, setSvcFail] = useState('')
  /* Список услуг врача этого визита — ответ сервера; `null` — ещё не пришёл
     (или не спрашивали), выбора на экране нет. */
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
     грязным навсегда. */
  const seeded = useRef(card.comment)

  useEffect(() => {
    if (open) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [open])

  useEffect(() => {
    /* ⚠️ Решение принимается ВНУТРИ обновления состояния: снаружи `text` —
       значение прошлого рендера, и черновик, набранный за кадр до ответа
       канала, считался бы чистым и был бы затёрт. */
    setText((cur) => {
      if (cur !== seeded.current) return cur      // тронули — не трогаем
      seeded.current = card.comment
      return card.comment
    })
  }, [card.comment])

  /* Спросить список при открытии — один раз на окно (другой визит — другое
     окно, экран пересоздаёт его по номеру). Отказ сети — выбора нет, а
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

  const info = [card.service, card.doctor, card.phone,
    card.age ? `${card.age} ani` : ''].filter(Boolean).join(' · ')
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

  /* Сохранённый комментарий закрывает окно, как исход визита (14.10, слово
     Олега: «вкладка по идее должна закрыться»); отказ оставляет окно с
     набранным. Отметка звонка окно держит — она часто идёт перед исходом. */
  async function save(e: FormEvent) {
    e.preventDefault()
    if (await onComment(text)) onClose()
  }

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
        <div className="dp-card-info">{info}</div>
        {card.pid ? (
          <>
            <AppLink className="dp-card-link" href={`/admin/patient/${card.pid}`}>
              <Icon name="id" /> {T.fisa}
            </AppLink>
            <AppLink className="dp-card-link"
               href={`/admin/visit/${id}?back=${encodeURIComponent(back)}`}>
              <Icon name="med" /> {card.rec ? T.visitOld : T.visitNew}
            </AppLink>
          </>
        ) : null}
        {card.callable && onCall && !note && (
          <div className="dp-card-call" role="group" aria-label={CALL_WORDS.call}>
            <span className="dp-card-call-l"><Icon name="phone" /> {CALL_WORDS.call}</span>
            {card.call && (
              <span className={card.call === 'ok' ? 'dk-ok' : 'dk-no'}>
                <Icon name={card.call === 'ok' ? 'check' : 'phone-off'} />
                {' '}{card.call === 'ok' ? CALL_WORDS.okDone : CALL_WORDS.noDone}
              </span>
            )}
            <span className="dp-card-call-b">
              {card.call !== 'ok' && (
                <button type="button" className="dk-btn ok" disabled={busy}
                  onClick={() => { void onCall('ok') }}><Icon name="check" /> {CALL_WORDS.ok}</button>
              )}
              {!card.call && (
                <button type="button" className="dk-btn no" disabled={busy}
                  onClick={() => { void onCall('noanswer') }}><Icon name="phone-off" /> {CALL_WORDS.no}</button>
              )}
              {card.call && (
                <button type="button" className="dk-btn" disabled={busy}
                  onClick={() => { void onCall('') }}><Icon name="undo" /> {CALL_WORDS.undo}</button>
              )}
            </span>
          </div>
        )}
        <form onSubmit={save} className="dp-card-cmt">
          <textarea value={text} rows={3} maxLength={300} placeholder={T.comment}
                    onChange={(e) => setText(e.target.value)} />
          <button disabled={busy}><Icon name="chat" /> {T.save}</button>
        </form>
        {/* Смена процедуры — ПОД комментарием: она редкая, а комментарий
            правят каждый день; и первой формой окна остаётся комментарий. */}
        {svcShown && (
          <form onSubmit={saveSvc} className="dp-card-svc" aria-label={T.svc}>
            {svcFail ? <div className="banner err" role="alert">{svcFail}</div> : null}
            <select value={svc} aria-label={T.svc}
                    onChange={(e) => { setSvc(e.target.value); setSvcFail('') }}>
              {svcKnown ? null : <option value={card.service_id} disabled>{card.service}</option>}
              {svcList.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
            <button disabled={busy || svc === card.service_id}>
              <Icon name="pen" /> {T.svcSave}
            </button>
          </form>
        )}
      </div>
      <div className="dlg-status">
        {actions.map((a) => (
          <form key={a.to} onSubmit={(e) => {
            e.preventDefault()
            void when(a.confirm, () => { void onStatus(a.to) })
          }}>
            <button className={`bstat ${a.cls}`} disabled={busy}>
              {a.cls === 'b-reopen' ? <><Icon name="undo" /> </> : null}{a.label}
            </button>
          </form>
        ))}
      </div>
    </dialog>
  )
}
