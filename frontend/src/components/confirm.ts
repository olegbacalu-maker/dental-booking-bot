import { useSyncExternalStore } from 'react'

/*
 * Вопрос перед необратимым действием — СВОИМ окном, а не `window.confirm`
 * (01.10, слово Олега: «перед любым удалением спросить» — и одним окном в
 * стиле программы, которое называет, что именно удаляется). Окно рисует
 * `ConfirmHost`, смонтированный один раз рядом с роутером; экраны зовут
 * `ask(...)` и ждут ответа, как ждали бы `window.confirm`.
 *
 * ⛔ Единственное место в клиенте, где законен `window.confirm`: запасной
 * путь, когда хоста нет (экран смонтирован голым, как в проверках). Правило
 * держит `test_structure` («подтверждение — своим окном»).
 * ⚠️ Вопрос один в каждый момент: новый `ask` до ответа на прежний закрывает
 * прежний отказом — два окна друг над другом не бывает.
 */

export interface AskOptions {
  /** Сам вопрос — с именем того, что удаляется: «Ștergeți documentul „X"?». */
  text: string
  title?: string
  /** Подпись кнопки согласия; по умолчанию «Da», у необратимого — «Șterge». */
  ok?: string
  cancel?: string
  /** Необратимое действие: красная кнопка, фокус на отказе. */
  danger?: boolean
}

export interface AskRequest extends AskOptions {
  id: number
}

let current: AskRequest | null = null
let resolveCurrent: ((v: boolean) => void) | null = null
let seq = 0
const listeners = new Set<() => void>()

function emit(): void {
  listeners.forEach((f) => f())
}

/** Задать вопрос; `true` — человек согласился. Строка = только текст. */
export function ask(opts: AskOptions | string): Promise<boolean> {
  const o: AskOptions = typeof opts === 'string' ? { text: opts } : opts
  if (listeners.size === 0) {
    // хоста нет — окно браузера, чтобы действие не прошло без вопроса вовсе
    return Promise.resolve(window.confirm(o.text))
  }
  settle(false)
  return new Promise<boolean>((resolve) => {
    current = { ...o, id: ++seq }
    resolveCurrent = resolve
    emit()
  })
}

/** Если вопрос есть — спросить, и только по согласию выполнить. Для кнопок
 *  с серверным текстом (`a.confirm`): пустой вопрос = действовать сразу. */
export async function when(question: string, run: () => void): Promise<void> {
  if (!question || await ask(question)) run()
}

/** Ответ на текущий вопрос (кнопка, Esc, закрытие окна). */
export function settle(v: boolean): void {
  const r = resolveCurrent
  current = null
  resolveCurrent = null
  if (r) {
    emit()
    r(v)
  }
}

function subscribe(f: () => void): () => void {
  listeners.add(f)
  return () => { listeners.delete(f) }
}

/** Текущий вопрос — для хоста. */
export function useAsk(): AskRequest | null {
  return useSyncExternalStore(subscribe, () => current, () => null)
}
