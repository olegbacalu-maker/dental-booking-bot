/**
 * Контракт ответа движка. Один конверт на все эндпоинты /api/* —
 * его строит core/layout.msg_json на сервере.
 *
 * ⛔ `code` — существующий код из core/layout.MSG_BANNER, а НЕ новая строка,
 * и `text` — его перевод для человека, сделанный ТАМ ЖЕ. Второго словаря
 * текстов в TypeScript быть не должно: клиент показывает `text` и красит по
 * `tone`, кодов не переводит. Это правило §7.4 спецификации и грабля, на
 * которую проект уже наступал дважды — один статус назывался тремя разными
 * словами в трёх местах.
 */
export type Tone = 'ok' | 'err' | 'warn'

export interface ApiEnvelope<T = unknown> {
  ok: boolean
  /** Код из MSG_BANNER — источник истины на сервере. Пустой у тихого успеха. */
  code: string
  /** Текст кода для человека. Пустой, если кода нет или его нет в словаре. */
  text: string
  tone: Tone
  /** Какое поле формы виновато, если ok = false и это отказ валидации. */
  field?: string
  data?: T
}

/** Почему запрос не удался. Разбор по причинам, а не по коду числом. */
export type ApiFailure =
  /** 401 — не вошёл или сессия истекла. Текста нет: человек уходит на вход. */
  | { kind: 'unauthenticated' }
  /** 403 — вошёл, но роль не пускает (PERMS на сервере) или чужой Origin. */
  | { kind: 'forbidden'; code: string; text: string }
  /** 422 — не прошла проверка. `field` называет поле формы. */
  | { kind: 'validation'; code: string; text: string; field?: string }
  /** 409 — конфликт: занятый слот, дубль пациента, запись уже уехала. */
  | { kind: 'conflict'; code: string; text: string }
  /** Сеть, таймаут, оборванный ответ. Программа продолжает работать. */
  | { kind: 'network'; detail: string }
  /** Движок ответил 500 или чем-то, чего контракт не предусматривает. */
  | { kind: 'server'; status: number; code: string; text: string }

export class ApiError extends Error {
  readonly failure: ApiFailure

  constructor(failure: ApiFailure, message: string) {
    super(message)
    this.name = 'ApiError'
    this.failure = failure
  }

  /** Код MSG_BANNER, если он есть. */
  get code(): string {
    return 'code' in this.failure ? this.failure.code : ''
  }

  /** Текст сервера для человека; пустой там, где сервера не было (сеть)
   *  или он ответил не словами (500 текстом от uvicorn). */
  get text(): string {
    return 'text' in this.failure ? this.failure.text : ''
  }

  /** Поле формы, которое отверг сервер. */
  get field(): string | undefined {
    return this.failure.kind === 'validation' ? this.failure.field : undefined
  }
}
