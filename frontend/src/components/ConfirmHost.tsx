import { useEffect, useRef } from 'react'
import { settle, useAsk } from './confirm'
import { hideDialog, showDialog } from './dialog'
import { Icon } from './Icon'
import { useLingering } from '../utils/motion'

/* Окно подтверждения — одно на всё приложение (см. `confirm.ts`). Тот же
   `<dialog>`, что у карточки визита и фиши: панель, подложка, радиусы из
   panel.css. Фокус — на отказе у необратимого (Enter не удаляет случайно) и
   на согласии у обычного вопроса. Esc и закрытие окна — отказ. */
const T = {
  ok: 'Da',
  okDanger: 'Șterge',
  cancel: 'Renunță',
} as const

export function ConfirmHost() {
  const req = useAsk()
  /* окно гаснет за ступень (07.11) — текст и кнопки стоят до конца, не пустеют */
  const { shown } = useLingering(req)
  const ref = useRef<HTMLDialogElement>(null)
  const okRef = useRef<HTMLButtonElement>(null)
  const noRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (req) {
      showDialog(d)
      ;(req.danger ? noRef : okRef).current?.focus()
    } else {
      hideDialog(d)
    }
  }, [req])

  return (
    <dialog ref={ref} className="dp-ask" aria-labelledby="dp-ask-text"
      onClose={() => settle(false)}>
      {shown && (
        <>
          <div className="dp-ask-body">
            <span className={`dp-ask-ico${shown.danger ? ' danger' : ''}`}>
              <Icon name={shown.danger ? 'trash' : 'help'} />
            </span>
            <div className="dp-ask-txt">
              {shown.title && <b>{shown.title}</b>}
              <p id="dp-ask-text">{shown.text}</p>
            </div>
          </div>
          <div className="dp-ask-btns">
            <button ref={noRef} type="button" className="pl-btn" onClick={() => settle(false)}>
              {shown.cancel ?? T.cancel}
            </button>
            <button ref={okRef} type="button" className={`savebtn${shown.danger ? ' dp-ask-danger' : ''}`}
              onClick={() => settle(true)}>
              {shown.ok ?? (shown.danger ? T.okDanger : T.ok)}
            </button>
          </div>
        </>
      )}
    </dialog>
  )
}
