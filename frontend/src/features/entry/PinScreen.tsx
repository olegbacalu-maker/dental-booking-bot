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
 * Из СЕТИ (не с ПК программы, 02.11) сервер одного PIN не сверяет: отвечает
 * `login_pick` со списком людей, и экран добавляет выбор человека над PIN
 * (набранный PIN остаётся). Выбор помнится в браузере устройства — только
 * чтобы стоять выбранным в следующий раз, сам по себе он не уходит: второй
 * компьютер кабинета делят несколько врачей.
 * ⛔ Решает сервер: верность PIN, счётчик неудач, блокировка, битый файл —
 * `POST /api/auth/login` тем же оракулом, что и форма; здесь только ввод и
 * текст отказа из конверта. Ни одного слова про PIN клиент не выдумывает.
 */

const T = t('pin', {
  pin: 'PIN',
  enter: 'Intră',
  checking: 'Se verifică…',
  forgot: 'Ați uitat PIN-ul? Un director îl poate schimba din Setări › Securitate și utilizatori, pe calculatorul cu programul.',
  offline: 'Programul nu răspunde. Reîncercați.',
  person: 'Persoana',
  pick: 'Alegeți persoana',
  by: 'DentPilot',
} as const)

interface Props {
  /** Модель оболочки на момент выхода: имя и логотип клиники, дверь, фон. */
  m: ShellModel
  /** Вход: бросает `ApiError` при отказе; удача — экран уберёт `App`.
   *  `uid` пустой, пока сервер не попросил выбрать человека (вход из сети). */
  enter: (pin: string, uid: string) => Promise<void>
}

interface Person { id: string; name: string }

const LAST = 'dp.pin.person'

function lastPerson(): string {
  try { return window.localStorage.getItem(LAST) ?? '' } catch { return '' }
}

function rememberPerson(id: string) {
  try { window.localStorage.setItem(LAST, id) } catch { /* профиль без хранилища */ }
}

/** Список людей из отказа `login_pick`; всё прочее — null. */
function peopleOf(data: unknown): Person[] | null {
  const list = (data as { people?: unknown } | undefined)?.people
  if (!Array.isArray(list)) return null
  return list.filter((p): p is Person =>
    typeof p === 'object' && p !== null && typeof (p as Person).id === 'string'
    && typeof (p as Person).name === 'string')
}

export function PinScreen({ m, enter }: Props) {
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<{ text: string; locked: boolean } | null>(null)
  const [people, setPeople] = useState<Person[] | null>(null)
  const [uid, setUid] = useState('')
  const field = useRef<HTMLInputElement>(null)
  const chooser = useRef<HTMLSelectElement>(null)
  /* Курсор — в PIN сразу, как `autofocus` у страницы входа: это форма входа,
     и человек у стойки набирает, не глядя. */
  useEffect(() => { field.current?.focus() }, [])

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setErr(null)
    try {
      if (uid) rememberPerson(uid)
      await enter(pin, uid)
      /* удача: `App` снимает замок, экран размонтирован — состояния нет */
    } catch (ex) {
      const er = asApiError(ex)
      setErr({ text: er.text || T.offline, locked: er.code === 'lock_pin' })
      setBusy(false)
      const list = er.code === 'login_pick' ? peopleOf(er.data) : null
      if (list) {
        /* ничего не сверялось — PIN остаётся набранным, нужен только выбор */
        const last = lastPerson()
        setPeople(list)
        if (list.some((p) => p.id === last)) setUid(last)
        setTimeout(() => chooser.current?.focus(), 0)
        return
      }
      setPin('')
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
        {people && (
          <select ref={chooser} name="uid" aria-label={T.person} required value={uid}
            onChange={(e) => { setUid(e.target.value); field.current?.focus() }}>
            <option value="" disabled>{T.pick}</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
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
