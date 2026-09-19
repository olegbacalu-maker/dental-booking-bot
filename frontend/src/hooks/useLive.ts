import { useCallback, useEffect, useRef, useState } from 'react'
import { LIVE_MS, nextLive, pollLive } from '../services/live'
import { loginUrl } from '../services/api'

/**
 * Живой экран: первая загрузка и опрос — ОДНИМ путём.
 *
 * ⛔ Отдельной «загрузки» тут нет намеренно. Два пути к одним данным — это два
 * места, где состав ответа разбирается по-своему, и они разойдутся; у старой
 * страницы этого не было по построению (тело и фрагмент считал один код), и
 * терять свойство на переезде нельзя.
 * ⚠️ Хук ничего не знает про панель: путь и поверхность приходят аргументами.
 * То, ЧТО делать с ответом, решает чистая `nextLive` (`services/live.ts`) —
 * здесь только таймер, видимость вкладки и хранение отпечатка.
 * ⛔ Поверхность и версия — ОТДЕЛЬНЫЕ строки, а не объект: объект-литерал от
 * вызывающего имеет новую ссылку на каждый рендер, и эффект перезапускался бы
 * вместе с таймером.
 */
export type LiveStatus = 'loading' | 'ready' | 'failed' | 'stopped' | 'leaving'

export interface LiveState<T> {
  status: LiveStatus
  data: T | null
  /** Почему опрос прекращён. Пусто, пока он идёт. */
  reason: 'broken' | 'not-live' | null
}

/* Вне хука, чтобы ссылки были стабильными: иначе эффект перезапускался бы на
   каждый рендер. Подменяются в проверках — jsdom не умеет переходов. */
export const defaultNavigate = (url: string) => window.location.assign(url)
export const defaultReload = () => window.location.reload()
const never = () => false
const noop = () => { /* тик ещё не подписан */ }

export interface LiveOptions {
  /**
   * Придержать ПРИМЕНЕНИЕ новых данных — предикат, а не значение.
   *
   * ⛔ Это НЕ «открыт диалог». Старый `panel.js` замораживал страницу на любом
   * открытом `<dialog>`, и рабочее место с забытой открытой карточкой
   * переставало узнавать о бронях со второго места, оставаясь живым НА ВИД.
   * Здесь придерживается ровно то, чему применение навредит ПРЯМО СЕЙЧАС:
   * человек тащит блок (данные увезли бы его из-под мыши) и команда в полёте
   * (ответ всё равно на подходе). Несохранённый черновик СВОИМ делом держит
   * диалог: экран под ним продолжает жить.
   * ⚠️ ПРЕДИКАТ, а не булев проп: проп попадает в хук через пассивный эффект,
   * и между нажатием и переписью есть кадр. Для перетаскивания это неважно, а
   * для команды длиной в круг по 127.0.0.1 — ровно та щель, ради которой
   * защита и ставится. Вызывающий ставит свой признак СИНХРОННО, в
   * обработчике, и предикат читает его в момент тика.
   * ⭐ Отказ применить НЕ ДВИГАЕТ отпечаток, поэтому ничего не теряется:
   * следующий тик принесёт то же самое.
   */
  hold?: () => boolean
  /** Период опроса; отдельным параметром только ради проверок. */
  everyMs?: number
  navigate?: (url: string) => void
  reload?: () => void
}

export function useLive<T>(
  path: string,
  surface: string,
  version: string,
  options: LiveOptions = {},
) {
  const { hold = never, everyMs = LIVE_MS,
    navigate = defaultNavigate, reload = defaultReload } = options
  const [state, setState] = useState<LiveState<T>>({
    status: 'loading', data: null, reason: null,
  })
  const [attempt, setAttempt] = useState(0)
  /* Отпечаток, «держим», «данные уже были» и переходы живут в ref, а не в
     зависимостях: от них не зависит картинка, а перезапуск эффекта сбрасывал
     бы таймер.
     ⛔ Особенно переходы. Вызывающий почти всегда передаёт стрелку прямо в
     аргументе, то есть НОВУЮ ссылку на каждый рендер; стой они в зависимостях
     — эффект пересоздавался бы после каждого ответа, а каждое пересоздание
     спрашивает сервер немедленно. Получается непрерывный опрос вместо раза в
     12 секунд: экран выглядит исправным, и заметить это можно только
     счётчиком запросов (поймано проверкой 19.09 — 252 запроса вместо одного). */
  const tag = useRef('')
  const loaded = useRef(false)
  /* Свежесть СОСТОЯНИЯ, а не порядок доставки. `sent` — номер последнего
     выпущенного запроса, `fresh` — номер того, чьё состояние уже на экране.
     ⛔ Без этого живёт гонка, от которой `hold` не спасает, потому что к
     моменту беды команда уже завершилась:
         тик №41 вылетел  →  команда изменила день  →  refresh() №42 привёз
         новое и применил  →  ответ №41 доставлен и кладёт ДОкомандное
         состояние поверх свежего.
     Визит исчезает с канвы на двенадцать секунд, и регистратура записывает
     второй раз. Правило простое: номер не больше применённого — выбросить. */
  const sent = useRef(0)
  const fresh = useRef(0)
  const ask = useRef<() => void>(noop)
  const now = useRef({ hold, navigate, reload })
  useEffect(() => { now.current = { hold, navigate, reload } })

  useEffect(() => {
    const ctl = new AbortController()
    const timers: { id?: ReturnType<typeof setInterval> } = {}
    let stopped = false

    const finish = () => {
      stopped = true
      if (timers.id !== undefined) clearInterval(timers.id)
    }

    const tick = async () => {
      if (stopped || document.hidden) return
      const mine = ++sent.current
      const res = await pollLive<T>(path, tag.current, ctl.signal)
      if (stopped || ctl.signal.aborted) return
      /* ⚠️ Предикат читается ЗДЕСЬ, в момент решения, а не при подписке. */
      const act = nextLive(res, { surface, version }, now.current.hold())
      switch (act.do) {
        case 'leave':
          finish()
          setState((s) => ({ ...s, status: 'leaving' }))
          now.current.navigate(loginUrl())
          return
        case 'reload':
          finish()
          now.current.reload()
          return
        case 'stop':
          finish()
          setState((s) => ({ ...s, status: 'stopped', reason: act.why }))
          return
        case 'apply':
          // ⛔ Ответ старее того, что уже на экране, — выбросить. Порядок
          // проверяется ТОЛЬКО здесь: «сессия кончилась», «чужая поверхность»
          // и «непонятный ответ» верны независимо от того, кто кого обогнал.
          if (mine <= fresh.current) return
          fresh.current = mine
          // ⛔ Отпечаток двигается ТОЛЬКО здесь, вместе с данными: сдвинь его
          // отдельно — и отказ применить (hold) потерял бы правку навсегда.
          tag.current = act.tag
          loaded.current = true
          setState({ status: 'ready', data: act.data, reason: null })
          return
        case 'keep':
          if (loaded.current) return       // молчим: движок перезапускается
          // ⚠️ 204 при пустом отпечатке невозможен (сервер сравнивает с тем,
          // чего клиент не присылал), но если он случился — показывать пустой
          // экран как готовый нельзя: сбрасываем отпечаток и ждём тика.
          if (res.kind === 'ok') { tag.current = ''; return }
          // Первая загрузка не удалась: показать нечего, и молчать нельзя.
          setState((s) => (s.status === 'loading' ? { ...s, status: 'failed' } : s))
      }
    }

    const wake = () => { if (!document.hidden) void tick() }
    /* Немедленный тик наружу. ⛔ Отпечаток он не трогает и данных не несёт:
       это ТОТ ЖЕ путь, а не второй. Ради этого команда и не возвращает
       состояния — иначе у экрана появилось бы два источника истины. */
    ask.current = () => { void tick() }

    void tick()
    timers.id = setInterval(() => void tick(), everyMs)
    document.addEventListener('visibilitychange', wake)
    return () => {
      finish()
      document.removeEventListener('visibilitychange', wake)
      ctl.abort()
    }
  }, [path, surface, version, everyMs, attempt])

  /** Повтор после неудачной ПЕРВОЙ загрузки. Отпечаток при этом не трогаем:
   *  данных на экране нет, и сравнивать не с чем. */
  const retry = useCallback(() => {
    loaded.current = false
    setState({ status: 'loading', data: null, reason: null })
    setAttempt((n) => n + 1)
  }, [])

  /** Спросить канал НЕМЕДЛЕННО — после своей команды. Отпечаток не трогает.
   *  ⛔ Единственное, что хук отдаёт наружу сверх состояния. `applyLive`,
   *  `applyData`, `setData` не заводить ни под каким предлогом: дверь для
   *  состояния одна, и держится это тем, что второй просто нет. */
  const refresh = useCallback(() => ask.current(), [])

  return { state, retry, refresh }
}
