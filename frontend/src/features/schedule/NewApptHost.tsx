import { useCallback, useEffect, useState } from 'react'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { asApiError, loginUrl } from '../../services/api'
import { AddDialog } from './AddDialog'
import { day, type DayForm, type NewAppt } from './day'

/* «Programare nouă» ВНЕ дня журнала — окно поверх того экрана, где стоишь
   (22.10, Олег: регистратура вносит записи врача в фишу первого пациента,
   приходит второй — она записывает его и остаётся в фише). До 22.10 кнопка
   шапки уводила на `/admin/all#addform`, и начатая фиша терялась.

   ⛔ Без перехода и без якоря: смена адреса на фише перезапускает её
   загрузчик и пишет лишнее «открыл фишу» в журнал доступа. Окно открывает
   СОСТОЯНИЕ оболочки (`AppShell` › `adding`), экран под ним не узнаёт о нём
   ничего.
   ⛔ Пациента экрана в окно НЕ подставлять: записывают другого человека.
   ⚠️ Форма — `GET /api/schedule/day` без даты: «сегодня» решает сервер в
   момент открытия (документ шапки мог загрузиться вчера), часы другой даты
   окно спрашивает само (`AddDialog`). Запись — без состояния
   (`day.record`, `screen=new_appt`): дня экрана у окна нет, в ответ — код и
   слово, а результат смотрят по ссылке плашки.
   На дне журнала окно своё (`DayScreen`, `#addform`), это — не оно. */

const T = {
  see: 'Vezi în jurnal ›',
  offline: 'Programul nu răspunde. Reîncercați.',
} as const

interface Props {
  open: boolean
  onClose: () => void
  /** Уход на вход при 401 — документом; подменяется в проверках. */
  navigate?: (url: string) => void
}

/** Окно записи и плашка его ответа. Плашка живёт ДОЛЬШЕ окна: окно закрыто
 *  удачей, а «Programare adăugată» ещё висит. */
export function NewApptHost({ open, onClose, navigate = defaultNavigate }: Props) {
  const [toast, setToast] = useState<ToastState | null>(null)
  const closeToast = useCallback(() => setToast(null), [])
  return (
    <>
      {open ? <NewApptWindow onClose={onClose} onDone={setToast} navigate={navigate} /> : null}
      {toast ? <Toast {...toast} onClose={closeToast} /> : null}
    </>
  )
}

interface WindowProps {
  onClose: () => void
  onDone: (t: ToastState) => void
  navigate: (url: string) => void
}

/** Смонтировано, пока окно открыто: каждое открытие — запись с чистого листа,
 *  как у окна дня журнала. */
function NewApptWindow({ onClose, onDone, navigate }: WindowProps) {
  const [got, setGot] = useState<{ date: string; form: DayForm } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const ctl = new AbortController()
    day.get('', '', '', ctl.signal).then(
      (r) => {
        if (ctl.signal.aborted) return
        if (r.data.form) {
          setGot({ date: r.data.date, form: r.data.form })
          return
        }
        /* у «Toți medicii» форма есть всегда (`_day_model`); нет — ответ не тот */
        onDone({ tone: 'err', text: T.offline })
        onClose()
      },
      (e: unknown) => {
        if (ctl.signal.aborted) return
        const err = asApiError(e)
        if (err.failure.kind === 'unauthenticated') {
          navigate(loginUrl())
          return
        }
        onDone({ tone: 'err', text: err.text || T.offline })
        onClose()
      },
    )
    return () => ctl.abort()
  }, [onClose, onDone, navigate])

  const add = async (body: NewAppt, fail: (text: string) => void): Promise<boolean> => {
    setBusy(true)
    try {
      const r = await day.record(body)
      /* слово и тон — сервера: `ok_past` и `ok_other` предупреждают и висят */
      onDone({ tone: r.tone, text: r.text, link: { href: `/admin/all?date=${body.date}`, label: T.see } })
      return true
    } catch (e) {
      const err = asApiError(e)
      if (err.failure.kind === 'unauthenticated') navigate(loginUrl())
      else fail(err.text || T.offline)
      return false
    } finally {
      setBusy(false)
    }
  }

  if (!got) return null
  return <AddDialog open form={got.form} date={got.date} of="" busy={busy} onClose={onClose} onAdd={add} />
}
