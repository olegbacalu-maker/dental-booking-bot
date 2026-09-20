import { useEffect, useRef } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import type { NoteView, StatusAction } from './day'

/* Диалог заметки стойки (C26.5.3-d): прочитать её ЦЕЛИКОМ и убрать.

   ⭐ Ради чего он вообще нужен: на панели полный текст заметки не виден
   НИГДЕ. В блоке 40 знаков, в подсказке 80, а хранится 120 (`_add_note`
   режет ввод именно там) — длинную заметку до этого шага на `/admin` было не
   прочитать вовсе, ни одним способом. Диалог показывает то, что лежит в базе.
   ⚠️ И это НОВОЕ поведение, а не перенос: у легаси-панели заметка не
   открывается ничем — у блока нет обработчика, а `panel.js` кликов по сетке
   не слушает. Названо планом 19.09 (`interaction-contract` › ступень `d`), и
   пришло оно сюда именно оттуда, а не «заодно».

   ⛔ Текста, который ПРАВЯТ, здесь нет: ни поля ввода, ни «Salvează». Заметка
   не редактируется нигде в программе — её текст пишется один раз при вставке,
   и ни один `UPDATE appointments` не трогает колонку `service`. Поле ввода
   завело бы правило, которого на сервере не существует, а изобретать его в
   шаге миграции запрещено.
   ⛔ Кнопка приходит С СЕРВЕРА (`note_actions[status]`) — той же матрицей, что
   печатает список дня. Своего списка в браузере нет: у заметки два состояния
   из шести («убрать» и «вернуть»), и разойдись они — на одном экране заметка
   теряла бы возврат, а на другом сохраняла.
   ⚠️ Вопрос подтверждения СЕРВЕРНЫЙ и по классу, а не по разрушительности:
   «Șterge» не спрашивает ничего, «Restabilește» спрашивает. Полярность
   обратная ожидаемой — и чинить её по дороге в React нельзя, это отдельное
   решение, а не уборка.
   ⚠️ Многочасовая блокировка — это N СТРОК по часу (`_add_note` вставляет по
   записи на каждый час), поэтому кнопка действует на ОДИН час, а не на весь
   интервал. Так же ведёт себя и список дня; здесь это названо, чтобы никто не
   починил «недоработку», которой нет.
   ⚠️ Отправка НЕОБЯЗАТЕЛЬНА, и это ступень: `d` заметку открывает и
   моделирует, команда — `e`. Без обработчика кнопка ЗАПЕРТА и над ней стоит
   объяснение.
   ⛔ Надгробие здесь ЕСТЬ, в отличие от пустого часа, и разница не в
   аккуратности: слот — место, а заметка — запись, и она исчезает из конверта,
   когда её убирают со второго рабочего места. Молча размонтировать нельзя —
   человек решит, что промахнулся мимо кнопки. Слово своё: у сервера его нет
   вовсе (`_set_status` отвечает пустым кодом), а чужое — «Programarea nu mai
   există» — назвало бы заметку программой. */
const T = {
  title: 'Notiță / blocare',
  close: 'Închide',
} as const

interface Props {
  open: boolean
  note: NoteView
  /** Кнопки по состоянию. ⛔ Приходят с сервера, второго словаря нет. */
  actions: StatusAction[]
  /** Непусто — заметки больше нет: её убрали со второго рабочего места.
   *  Кнопок в этом случае не приходит вовсе (надгробие, как у карточки). */
  gone?: string
  /** Непусто — объяснение над текстом: отправить отсюда пока некуда. */
  notice?: string
  busy: boolean
  onClose: () => void
  onStatus?: (to: string) => Promise<boolean>
}

export function NoteDialog({ open, note, actions, gone = '', notice = '', busy,
  onClose, onStatus }: Props) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    if (open) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [open])

  return (
    <dialog ref={ref} onClose={onClose}>
      <div className="dlg-head">
        <span><Icon name="note" /> {T.title}</span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <div className="dlg-form">
        {gone && <div className="banner err" role="alert">{gone}</div>}
        {notice && <div className="banner warn">{notice}</div>}
        <div className="dp-card-info">{note.time} · {note.dur}′</div>
        {/* ⛔ Именно текст, а не `<textarea>`: поле ввода — обещание правки. */}
        <p className="dp-note-text">{note.text}</p>
      </div>
      <div className="dlg-status">
        {actions.map((a) => (
          <form key={a.to} onSubmit={(e) => {
            e.preventDefault()
            if (!onStatus) return
            if (a.confirm && !window.confirm(a.confirm)) return
            void onStatus(a.to)
          }}>
            <button className={`bstat ${a.cls}`} disabled={busy || !onStatus}>
              {a.cls === 'b-reopen' ? <><Icon name="undo" /> </> : null}{a.label}
            </button>
          </form>
        ))}
      </div>
    </dialog>
  )
}
