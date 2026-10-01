import { useEffect, useRef } from 'react'
import { settle, useAsk } from './confirm'
import { hideDialog, showDialog } from './dialog'
import { Icon } from './Icon'

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
      {req && (
        <>
          <div className="dp-ask-body">
            <span className={`dp-ask-ico${req.danger ? ' danger' : ''}`}>
              <Icon name={req.danger ? 'trash' : 'help'} />
            </span>
            <div className="dp-ask-txt">
              {req.title && <b>{req.title}</b>}
              <p id="dp-ask-text">{req.text}</p>
            </div>
          </div>
          <div className="dp-ask-btns">
            <button ref={noRef} type="button" className="pl-btn" onClick={() => settle(false)}>
              {req.cancel ?? T.cancel}
            </button>
            <button ref={okRef} type="button" className={`savebtn${req.danger ? ' dp-ask-danger' : ''}`}
              onClick={() => settle(true)}>
              {req.ok ?? (req.danger ? T.okDanger : T.ok)}
            </button>
          </div>
        </>
      )}
    </dialog>
  )
}
