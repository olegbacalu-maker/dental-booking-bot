/**
 * Единственная точка разговора с движком.
 *
 * §6 спецификации: компоненты в сеть не ходят. Всё через этот модуль — иначе
 * проверки прав, разбор конверта и обработка истёкшей сессии расползутся по
 * сорока экранам и разойдутся между собой.
 */
import { ApiError, type ApiEnvelope, type ApiFailure, type Tone } from '../types/api'

/**
 * Адреса ОТНОСИТЕЛЬНЫЕ, и базового URL здесь нет намеренно.
 *
 * Страницу отдаёт тот же FastAPI, что и API, поэтому origin у браузера один.
 * На этом держатся сразу три вещи в движке:
 *   · кука admin_auth ходит с samesite=lax — на чужой origin она бы не ушла;
 *   · same_origin_post сверяет Origin с Host и иначе отвечает 403 (core/auth.py);
 *   · client_is_local() отличает своё рабочее место от телефона в LAN.
 * ⛔ Захардкоженный `http://127.0.0.1:8088` сломал бы и LAN, и любой порт,
 * заданный клиникой через DENTART_PORT.
 */
const API_ROOT = '/api'

const JSON_HEADERS = { 'Content-Type': 'application/json' } as const

export interface RequestOptions {
  signal?: AbortSignal
  /** Тело запроса. Сериализуется в JSON. */
  body?: unknown
}

/**
 * Удачный ответ: данные плюс то, что сервер сказал словами. `text` — перевод
 * кода из MSG_BANNER, сделанный на сервере; экран показывает его как есть.
 */
export interface ApiResult<T> {
  data: T
  code: string
  text: string
  tone: Tone
}

async function request<T>(
  method: 'GET' | 'POST',
  path: string,
  options: RequestOptions = {},
): Promise<ApiResult<T>> {
  let response: Response
  try {
    response = await fetch(`${API_ROOT}${path}`, {
      method,
      credentials: 'same-origin',
      // ⛔ Редиректы НЕ глотать. Маршруты журнала на неавторизованный запрос
      // отвечают 303 на /admin/login, и обычный fetch сходил бы по нему и
      // вернул HTTP 200 с HTML формы входа. Экран показал бы пустоту вместо
      // «сессия истекла», а регистратура решила бы, что у пациента нет
      // записей. С 'manual' такой ответ приходит как opaqueredirect и ниже
      // превращается в честный отказ. /api/* отвечает 401 сам (core/api.py),
      // но страховка остаётся: она стоит одну строку.
      redirect: 'manual',
      ...(options.signal ? { signal: options.signal } : {}),
      ...(options.body === undefined
        ? {}
        : { headers: JSON_HEADERS, body: JSON.stringify(options.body) }),
    })
  } catch (error) {
    // Движок не ответил. Программа при этом жива — падать нельзя.
    throw fail({ kind: 'network', detail: String(error) })
  }

  if (response.type === 'opaqueredirect' || response.status === 0) {
    throw fail({ kind: 'unauthenticated' })
  }

  const envelope = await readEnvelope<T>(response)

  if (response.ok && envelope?.ok) {
    return {
      data: envelope.data as T,
      code: envelope.code,
      text: envelope.text ?? '',
      tone: envelope.tone ?? 'ok',
    }
  }

  const code = envelope?.code ?? ''
  const text = envelope?.text ?? ''
  switch (response.status) {
    case 401:
      throw fail({ kind: 'unauthenticated' })
    case 403:
      throw fail({ kind: 'forbidden', code, text })
    case 409:
      throw fail({ kind: 'conflict', code, text })
    case 422:
      throw fail({
        kind: 'validation',
        code,
        text,
        ...(envelope?.field ? { field: envelope.field } : {}),
      })
    default:
      throw fail({ kind: 'server', status: response.status, code, text })
  }
}

/** Тело может оказаться не-JSON: 500 от uvicorn приходит текстом. */
async function readEnvelope<T>(response: Response): Promise<ApiEnvelope<T> | null> {
  const type = response.headers.get('content-type') ?? ''
  if (!type.includes('application/json')) return null
  try {
    return (await response.json()) as ApiEnvelope<T>
  } catch {
    return null
  }
}

function fail(failure: ApiFailure): ApiError {
  return new ApiError(failure, describe(failure))
}

/**
 * ⚠️ Это текст для ЛОГА и для разработчика, а не для клиники. Человеку
 * показывается `text` из конверта: переводом занимается сервер, он же
 * единственный владелец MSG_BANNER.
 */
function describe(failure: ApiFailure): string {
  switch (failure.kind) {
    case 'unauthenticated':
      return 'session expired'
    case 'forbidden':
      return `forbidden: ${failure.code}`
    case 'validation':
      return `validation: ${failure.code}${failure.field ? ` (${failure.field})` : ''}`
    case 'conflict':
      return `conflict: ${failure.code}`
    case 'network':
      return `network: ${failure.detail}`
    case 'server':
      return `server ${failure.status}: ${failure.code}`
  }
}

/**
 * Куда отправить человека при 401: на экран входа движка с возвратом сюда —
 * ровно туда, куда HTML-охрана (_guard) шлёт редиректом. Экран входа
 * серверный намеренно: он обязан открываться и без бандла.
 */
export function loginUrl(): string {
  const back = window.location.pathname + window.location.search
  return `/admin/login?next=${encodeURIComponent(back)}`
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>('GET', path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('POST', path, { ...options, body }),
}
