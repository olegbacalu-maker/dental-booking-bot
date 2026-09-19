/**
 * Живой канал ДАННЫМИ: транспорт и правило «что делать с ответом».
 *
 * ⛔ Почему не `api.request` (`api.ts`). У живого канала четыре исхода, и два
 * из них БЕЗ ТЕЛА. `request` этого не умеет и не должен: он обслуживает
 * девятнадцать экранов, а 204 сегодня падает у него в `default:` и приезжает
 * как `server 204`, то есть «ошибка сервера» на самом частом ответе живого
 * журнала. Плюс канал обязан слать и читать СВОИ заголовки (`X-DP-Hash`,
 * `X-DP-V`, `X-DP-Surface`), а `request` собирает заголовки только из
 * `JSON_HEADERS`. Развести их — дешевле, чем научить один общий вход четырём
 * исходам и трём заголовкам.
 *
 * ⭐ Свойство, ради которого весь канал и делался: **второго рендера «для
 * опроса» не существует**. У старой страницы это держалось построением —
 * `data-hash` обёртки и `X-DP-Hash` фрагмента считались от одной строки. У
 * React держится тем же, только проще: страница с флагом НЕ несёт встроенного
 * состояния вовсе (проверено пином), первый запрос этого модуля и есть первое
 * состояние экрана. Второго сериализатора нет, потому что он один.
 */
import { type ApiEnvelope } from '../types/api'

/**
 * Период опроса. ⚠️ Число ДВА раза в программе — здесь и в `data-reload="12"`
 * на `<body>` живой СТАРОЙ страницы (`core/layout.py`). Это принято явно:
 * у React-панели атрибута нет вовсе (сервер не объявляет её живой), а сторож
 * потребовал бы константы в `layout` и строки в `mutate.py` ради величины,
 * расхождение которой проявится только частотой опроса.
 */
export const LIVE_MS = 12_000

/** Снимок ответа канала. `fresh: false` — это 204 «состояние прежнее». */
export interface LivePoll<T> {
  fresh: boolean
  data: T | null
  /** Отпечаток состояния: его же клиент пришлёт следующим запросом. */
  tag: string
  /** Версия программы. Разошлась со своей — exe обновили под открытой вкладкой. */
  version: string
  /** Какую поверхность сервер отдаёт по этому адресу: `react` или `legacy`. */
  surface: string
}

/**
 * Исход запроса. ⛔ Ни один из них не исключение: живой опрос идёт весь день,
 * и «сервер перезапускается при обновлении» — это не ошибка экрана.
 */
export type LiveResult<T> =
  | { kind: 'ok'; poll: LivePoll<T> }
  /** 401 или редирект на форму входа: сессия кончилась. */
  | { kind: 'signout' }
  /** Сеть молчит или движок отвечает не тем: молча ждём следующего тика. */
  | { kind: 'offline' }
  /** Ответ, которого клиент не понимает (422 и подобное): опрос прекращаем. */
  | { kind: 'broken'; status: number }

const LIVE_TAG = 'X-DP-Hash'
const LIVE_V = 'X-DP-V'
const LIVE_SURFACE = 'X-DP-Surface'

/** Один запрос живого канала. Путь — без `/api`, как у `api.get`. */
export async function pollLive<T>(
  path: string,
  tag: string,
  signal?: AbortSignal,
): Promise<LiveResult<T>> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      method: 'GET',
      credentials: 'same-origin',
      // ⛔ Редирект не глотать: без этого 303 на форму входа приехал бы как
      // 200 с HTML, `JSON.parse` упал бы в catch, и опрос замер бы МОЛЧА —
      // панель осталась бы живой на вид, показывая вчерашний день.
      redirect: 'manual',
      // ⛔ У WebView2 и у туннеля свои кеши; без этого «не менялось» можно
      // получить от кеша, а не от движка.
      cache: 'no-store',
      ...(signal ? { signal } : {}),
      ...(tag ? { headers: { [LIVE_TAG]: tag } } : {}),
    })
  } catch {
    return { kind: 'offline' }
  }

  if (response.type === 'opaqueredirect' || response.status === 401) {
    return { kind: 'signout' }
  }

  const head = (name: string) => response.headers.get(name) ?? ''
  const meta = { tag: head(LIVE_TAG), version: head(LIVE_V), surface: head(LIVE_SURFACE) }

  // ⭐ 204 — это и есть неподвижность экрана, а не пустой ответ. Заголовки на
  // нём приезжают те же, поэтому откат виден и в день, когда не менялось
  // ничего (`core/api.live_reply`).
  if (response.status === 204) return { kind: 'ok', poll: { fresh: false, data: null, ...meta } }

  if (response.status !== 200) {
    // 5xx — движок перезапускается после тихого обновления: это «подождать», а
    // не «сломалось». 4xx — клиент просит то, чего сервер не понимает.
    return response.status >= 500
      ? { kind: 'offline' }
      : { kind: 'broken', status: response.status }
  }

  let envelope: ApiEnvelope<T> | null
  try {
    envelope = (await response.json()) as ApiEnvelope<T>
  } catch {
    return { kind: 'offline' }
  }
  if (!envelope?.ok || envelope.data === undefined) return { kind: 'offline' }
  return { kind: 'ok', poll: { fresh: true, data: envelope.data, ...meta } }
}

/** Что экран обязан сделать с ответом. */
export type LiveAction<T> =
  /** Ничего: состояние прежнее, или связи нет, или человек сейчас тащит. */
  | { do: 'keep' }
  | { do: 'apply'; data: T; tag: string }
  /** Полная перезагрузка адреса: под вкладкой поменялось то, что она не может
   *  доиграть сама — версия программы или сама поверхность экрана. */
  | { do: 'reload'; why: 'version' | 'surface' }
  /** Сессия кончилась: уходим на вход. */
  | { do: 'leave' }
  /** Опрос прекращаем и говорим об этом словом, а не молчим. */
  | { do: 'stop'; why: 'broken' | 'not-live' }

export interface LiveSelf {
  /** Поверхность ЭТОГО клиента. У React-панели — `react`. */
  surface: string
  /** Версия, с которой загружена страница: `document.body.dataset.v`. */
  version: string
}

/**
 * Правило живого канала — чистая функция, без DOM и без таймеров.
 *
 * ⛔ Порядок веток несущий, и `hold` стоит выше перезагрузок намеренно:
 * человек держит блок мышью, и выдёргивать из-под него страницу нельзя.
 * Отложить безопасно ровно потому, что отказ применить НЕ ДВИГАЕТ отпечаток
 * (вызывающий не трогает `tag` на `keep`), и следующий тик принесёт то же
 * самое. Это свойство старого `panel.js`, и оно перенесено буквально.
 */
export function nextLive<T>(
  res: LiveResult<T>,
  self: LiveSelf,
  hold = false,
): LiveAction<T> {
  if (res.kind === 'signout') return { do: 'leave' }
  if (res.kind === 'offline') return { do: 'keep' }
  if (res.kind === 'broken') return { do: 'stop', why: 'broken' }
  if (hold) return { do: 'keep' }

  const { poll } = res
  // ⛔ Версия — раньше состояния: после тихого обновления exe новые данные
  // нельзя вклеивать в страницу со старым кодом и старым CSS.
  if (poll.version && self.version && poll.version !== self.version) {
    return { do: 'reload', why: 'version' }
  }
  // ⭐ Вторая половина отката: директор выключил флаг, и сервер отдаёт по
  // этому адресу старую страницу. Узнать об этом вкладка может только отсюда.
  if (poll.surface && poll.surface !== self.surface) {
    return { do: 'reload', why: 'surface' }
  }
  if (!poll.fresh) return { do: 'keep' }
  // ⚠️ `live:false` по проводу сегодня недостижим (C26.5.2: `live` — имя того
  // же факта, что и состав конверта). Ветка оставлена ЯВНОЙ, потому что
  // молчаливый экран, переставший обновляться, неотличим от работающего.
  const data = poll.data as (T & { live?: boolean }) | null
  if (data && data.live === false) return { do: 'stop', why: 'not-live' }
  if (data === null) return { do: 'keep' }
  return { do: 'apply', data, tag: poll.tag }
}
