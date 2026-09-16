/**
 * Контракт ответа движка. Один конверт на все эндпоинты /api/*.
 *
 * ⛔ `code` — это существующий код из core/layout.MSG_BANNER (90 штук), а НЕ
 * новая строка. Второго словаря текстов в TypeScript быть не должно: тексты
 * живут на сервере, клиент получает код и показывает то, что пришло.
 * Это правило §7.4 спецификации и грабля, на которую проект уже наступал
 * дважды — один статус назывался тремя разными словами в трёх местах.
 */
export interface ApiEnvelope<T = unknown> {
  ok: boolean
  /** Код из MSG_BANNER — источник истины на сервере. */
  code: string
  /** Какое поле формы виновато, если ok = false и это отказ валидации. */
  field?: string
  data?: T
}

/** Почему запрос не удался. Разбор по причинам, а не по коду числом. */
export type ApiFailure =
  /** 401 — не вошёл или сессия истекла. */
  | { kind: 'unauthenticated' }
  /** 403 — вошёл, но роль не пускает (PERMS на сервере). */
  | { kind: 'forbidden'; code: string }
  /** 422 — не прошла проверка. `field` называет поле формы. */
  | { kind: 'validation'; code: string; field?: string }
  /** 409 — конфликт: занятый слот, дубль пациента, запись уже уехала. */
  | { kind: 'conflict'; code: string }
  /** Сеть, таймаут, оборванный ответ. Программа продолжает работать. */
  | { kind: 'network'; detail: string }
  /** Движок ответил 500 или чем-то, чего контракт не предусматривает. */
  | { kind: 'server'; status: number; detail: string }

export class ApiError extends Error {
  readonly failure: ApiFailure

  constructor(failure: ApiFailure, message: string) {
    super(message)
    this.name = 'ApiError'
    this.failure = failure
  }

  /** Код MSG_BANNER, если он есть — для баннера на экране. */
  get code(): string | undefined {
    return 'code' in this.failure ? this.failure.code : undefined
  }
}
