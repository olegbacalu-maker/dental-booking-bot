import { useEffect, useRef, useState, type FormEvent } from 'react'
import { AppLink } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import type { StatusAction, VisitCardView } from './day'

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
  onComment: (text: string) => Promise<boolean>
  onStatus: (to: string) => Promise<boolean>
}

export function CardDialog({ open, id, card, actions, note = '', back, busy,
  onClose, onComment, onStatus }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [text, setText] = useState(card.comment)
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

  const info = [card.service, card.doctor, card.phone,
    card.age ? `${card.age} ani` : ''].filter(Boolean).join(' · ')

  async function save(e: FormEvent) {
    e.preventDefault()
    await onComment(text)
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
        <form onSubmit={save} className="dp-card-cmt">
          <textarea value={text} rows={3} maxLength={300} placeholder={T.comment}
                    onChange={(e) => setText(e.target.value)} />
          <button disabled={busy}><Icon name="chat" /> {T.save}</button>
        </form>
      </div>
      <div className="dlg-status">
        {actions.map((a) => (
          <form key={a.to} onSubmit={(e) => {
            e.preventDefault()
            if (a.confirm && !window.confirm(a.confirm)) return
            void onStatus(a.to)
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
