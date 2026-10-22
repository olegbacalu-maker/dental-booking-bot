import { useEffect, useRef, useState, type FormEvent } from 'react'
import type { ShellModel } from '../../layouts/shell'
import { asApiError } from '../../services/api'
import { t } from '../../utils/i18n'

/*
 * Экран PIN внутри программы (B4.4, 16.10.2026): смена человека у стойки.
 *
 * Та же карточка, что у страницы входа сервера (`modules/entry/pages.py ›
 * LOGIN_TMPL`): логотип клиники, её имя, PIN, «Intră», на том же фоне
 * (`entry.backdrop` — строка сервера). Рисуется ВМЕСТО журнала (`App`):
 * прошлого человека в окне нет ни узлом, ни запросом.
 * Поля «ID (opțional)» нет с 22.10.2026 (Олег): PIN уникален на всю клинику
 * (`auth.pin_free`), и сервер находит человека по одному PIN; `uid` в дверь
 * уходит пустым — `POST /api/auth/login` его по-прежнему принимает.
 * ⛔ Решает сервер: верность PIN, счётчик неудач, блокировка, битый файл —
 * `POST /api/auth/login` тем же оракулом, что и форма; здесь только ввод и
 * текст отказа из конверта. Ни одного слова про PIN клиент не выдумывает.
 */

const T = t('pin', {
  pin: 'PIN',
  enter: 'Intră',
  checking: 'Se verifică…',
  forgot: 'Ați uitat PIN-ul? Un director îl poate schimba din Setări › Securitate și utilizatori.',
  offline: 'Programul nu răspunde. Reîncercați.',
  by: 'DentPilot',
} as const)

interface Props {
  /** Модель оболочки на момент выхода: имя и логотип клиники, дверь, фон. */
  m: ShellModel
  /** Вход: бросает `ApiError` при отказе; удача — экран уберёт `App`.
   *  `uid` всегда пустой: поля на экране нет, подпись — договор `App`/`auth.login`. */
  enter: (pin: string, uid: string) => Promise<void>
}

export function PinScreen({ m, enter }: Props) {
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<{ text: string; locked: boolean } | null>(null)
  const field = useRef<HTMLInputElement>(null)
  /* Курсор — в PIN сразу, как `autofocus` у страницы входа: это форма входа,
     и человек у стойки набирает, не глядя. */
  useEffect(() => { field.current?.focus() }, [])

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setErr(null)
    try {
      await enter(pin, '')
      /* удача: `App` снимает замок, экран размонтирован — состояния нет */
    } catch (ex) {
      const er = asApiError(ex)
      setErr({ text: er.text || T.offline, locked: er.code === 'lock_pin' })
      setPin('')
      setBusy(false)
      field.current?.focus()
    }
  }

  return (
    <div className="dp-lock">
      {/* фон страниц входа — SVG сервера, как знак в сайдбаре */}
      <div dangerouslySetInnerHTML={{ __html: m.entry.backdrop }} />
      <form className="dp-lock-card" onSubmit={(e) => void submit(e)} aria-busy={busy}>
        {m.clinic.logo && <img className="clogo" src={m.clinic.logo} alt="" />}
        <h1>{m.clinic.name}</h1>
        {err && (
          <div className="err" role="alert">
            {err.text}
            {/* после смены пароля коллегой человек перебирает «верный» PIN и
                не знает, что делать, — выход, как на странице входа */}
            {err.locked && <><br /><small>{T.forgot}</small></>}
          </div>
        )}
        <input ref={field} type="password" name="password" placeholder={T.pin} aria-label={T.pin}
          required inputMode="numeric" pattern="[0-9]*" maxLength={m.entry.pin_max}
          className="dp-lock-pin" value={pin} onChange={(e) => setPin(e.target.value)} />
        <button type="submit" className="savebtn" disabled={busy}>{busy ? T.checking : T.enter}</button>
      </form>
      <div className="dp-by">
        <span dangerouslySetInnerHTML={{ __html: m.frame.site.mark }} />
        <span>{T.by} v{m.runtime.version}</span>
      </div>
    </div>
  )
}
