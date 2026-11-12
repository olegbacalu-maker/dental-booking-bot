import { useEffect, useRef, useState } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import { MinPick } from './MinPick'
import { clashAmong, hhmm, sameSlot, type Drag, type Occupies, type Target } from './move'
import { takenMinutes } from './slot'

/* Подтверждение переноса (C25.5b). Диалог обязателен: перетащить мышью легко
   случайно, а визит — это человек, которому уже назвали время.

   ⚠️ Строка «De la» стоит здесь не для красоты: если блок уехал не туда,
   вернуть его можно, только зная, откуда он.
   ⚠️ Предупреждение о занятости — ПОДСКАЗКА. Правду говорит сервер под
   `_BOOK_LOCK`: пока тянули, час мог занять второй администратор.
   Имена колонок и блоки колонки-цели даёт ЭКРАН готовыми: у дня и у панели
   РАЗНЫЕ модели (и разный ключ колонки), а диалог переноса один на оба. Прими
   он модель — пришлось бы заводить второй, и «De la» на одном экране
   разошлось бы с другим после переименования врача.
   Бросок даёт час и грубую половину, точную минуту доводят здесь: рукой в
   пять минут на сетке не попасть. Час и врач остаются теми, куда бросили. */
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
  /** Занятые блоки колонки-цели по канве — подсказка, а не запрет сервера. */
  taken: Occupies[]
  /** Шаг сетки стартов, минут. */
  step?: number | undefined
  busy: boolean
  onClose: () => void
  /** Минута от полуночи, выбранная в окне. */
  onMove: (min: number) => void
}

export function MoveDialog({ open, drag, target, fromName, toName, taken, step = 5, busy,
  onClose, onMove }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const hour = Math.floor(target.min / 60)
  const [minute, setMinute] = useState(target.min % 60)
  const min = hour * 60 + minute
  const off = takenMinutes(taken, hour, drag.dur, step, drag.id)
  const busyAt = clashAmong(taken, min, drag.dur, drag.id)
  /* своё же место: сервер такой перенос принял бы и записал в летопись */
  const same = sameSlot(drag, { dk: target.dk, min })

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
          <div><span>{T.to}</span><b>{toName} · {hhmm(min)}</b></div>
        </div>
        <MinPick hh={String(hour).padStart(2, '0')} value={minute} step={step} taken={off}
                 onPick={setMinute} />
        {busyAt >= 0 ? (
          <div className="banner err" role="alert">
            Medicul are deja o programare la {hhmm(busyAt)}.
          </div>
        ) : null}
        <div className="mv-act">
          <button type="button" className="mv-no" onClick={onClose}>{T.no}</button>
          <button type="button" onClick={() => onMove(min)} disabled={busy || busyAt >= 0 || same}>
            {T.yes}
          </button>
        </div>
      </div>
    </dialog>
  )
}
