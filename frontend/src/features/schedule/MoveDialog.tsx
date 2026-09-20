import { useEffect, useRef } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import { hhmm, type Drag, type Target } from './move'

/* Подтверждение переноса (C25.5b). Диалог обязателен: перетащить мышью легко
   случайно, а визит — это человек, которому уже назвали время.

   ⚠️ Строка «De la» стоит здесь не для красоты: если блок уехал не туда,
   вернуть его можно, только зная, откуда он.
   ⚠️ Предупреждение о занятости — ПОДСКАЗКА. Правду говорит сервер под
   `_BOOK_LOCK`: пока тянули, час мог занять второй администратор.
   ⭐ Имена колонок и минуту помехи считает ЭКРАН и передаёт готовыми: у дня
   и у панели РАЗНЫЕ модели (и разный ключ колонки), а диалог переноса один на
   оба. Прими он модель — пришлось бы заводить второй, и «De la» на одном
   экране разошлось бы с другим после переименования врача. */
const T = {
  title: 'Mutare programare',
  who: 'Pacient',
  from: 'De la',
  to: 'La',
  no: 'Anulează',
  yes: 'Da, mută',
  close: 'Închide',
} as const

interface Props {
  open: boolean
  drag: Drag
  target: Target
  /** Имя колонки, ИЗ которой тащат, и той, КУДА. */
  fromName: string
  toName: string
  /** Минута помехи или −1 — подсказка, а не запрет со стороны сервера. */
  busyAt: number
  busy: boolean
  onClose: () => void
  onMove: () => void
}

export function MoveDialog({ open, drag, target, fromName, toName, busyAt, busy,
  onClose, onMove }: Props) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    if (open) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [open])


  return (
    <dialog ref={ref} onClose={onClose}>
      <div className="dlg-head">
        <span>{T.title}</span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <div className="dlg-form">
        <div className="mv-rows">
          <div><span>{T.who}</span><b>{drag.nm}</b></div>
          <div><span>{T.from}</span><b>{fromName} · {hhmm(drag.min)}</b></div>
          <div><span>{T.to}</span><b>{toName} · {hhmm(target.min)}</b></div>
        </div>
        {busyAt >= 0 ? (
          <div className="banner err" role="alert">
            Medicul are deja o programare la {hhmm(busyAt)}.
          </div>
        ) : null}
        <div className="mv-act">
          <button type="button" className="mv-no" onClick={onClose}>{T.no}</button>
          <button type="button" onClick={onMove} disabled={busy || busyAt >= 0}>
            {T.yes}
          </button>
        </div>
      </div>
    </dialog>
  )
}
