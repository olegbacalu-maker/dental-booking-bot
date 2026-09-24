import { useCallback, useState, type ReactElement } from 'react'
import {
  useLoaderData, useNavigation, useRevalidator, type LoaderFunctionArgs, type Params,
  type RouteObject, type ShouldRevalidateFunction,
} from 'react-router'
import { asApiError, loginUrl, type ApiResult } from '../services/api'
import type { ApiError } from '../types/api'
import { defaultNavigate, type LoadState } from './useLoad'

/**
 * Загрузка данных экрана РОУТЕРОМ (B2.2) — тот же цикл, что у `useLoad`, но
 * запрос уходит в момент выбора маршрута, а не после первой отрисовки.
 */

/**
 * Что экран просит у движка: сигнал отмены роутера, параметры ПУТИ и query
 * ТЕКУЩЕГО адреса (B2.3). ⛔ Не параметры узла: узел описывает документ,
 * а после перехода роутером адрес уже другой.
 */
export type RouteLoad<T> = (signal: AbortSignal, params: Params, search: URLSearchParams) =>
  Promise<ApiResult<T>>

/**
 * Загрузчик экрана и, если нужно, своё правило перезапуска. Правило нужно
 * тому экрану, который часть адреса обслуживает САМ, без полной перезагрузки
 * (фиша: `?views=1` приносит только ленту — полная перезагрузка писала бы в
 * журнал доступа лишнее «открыл фишу»).
 */
export type ScreenData = RouteLoad<unknown> | {
  load: RouteLoad<unknown>
  shouldRevalidate: ShouldRevalidateFunction
}

/**
 * Правило для экрана, который смену query на том же пути обслуживает САМ:
 * загрузчик не перезапускается, повтор (тот же адрес) и другой путь — как
 * обычно. Поиск: сводка над списком — «один раз на открытие экрана»
 * (`/api/patients/summary`), а отбор тянет только страницу списка.
 */
export const searchChangeKeepsData: ShouldRevalidateFunction = ({ currentUrl, nextUrl, defaultShouldRevalidate }) =>
  currentUrl.pathname === nextUrl.pathname && currentUrl.search !== nextUrl.search
    ? false : defaultShouldRevalidate

/**
 * ⭐ Загрузчик отдаёт ту же `LoadState`, что и `useLoad`, и НЕ бросает на
 * отказе сервера: брошенное ушло бы в ловушку ошибок маршрута, и экран
 * потерял бы свою плашку отказа с повтором и ссылкой на старую страницу.
 * Бросает он только то, чего не ждёт никто, — это и есть работа ловушки.
 */
export function routeLoader<T>(load: RouteLoad<T>, navigate: (url: string) => void = defaultNavigate) {
  return async ({ request, params }: LoaderFunctionArgs): Promise<LoadState<T>> => {
    try {
      const r = await load(request.signal, params, new URL(request.url).searchParams)
      return { status: 'ready', data: r.data }
    } catch (e) {
      const err = asApiError(e)
      if (err.failure.kind === 'unauthenticated') {
        navigate(loginUrl())
        return { status: 'leaving' }
      }
      return { status: 'failed', error: err }
    }
  }
}

/**
 * Маршрут экрана. ⛔ Загрузчик без `hydrateFallbackElement` здесь собрать
 * НЕЛЬЗЯ: роутер нарисовал бы на время ожидания вместо корня `null`, и вместе
 * с экраном пропала бы оболочка (стенд scripts/loader_hold.py, B2.2).
 * ⭐ Первый кадр — ТОТ ЖЕ экран: пока данных нет, `useRouteLoad` отдаёт
 * загрузку, и экран рисует своё обычное ожидание. Отдельной «заглушки»,
 * которая разошлась бы с экраном, не существует.
 */
export function screenRoute(
  path: string, element: ReactElement, data?: ScreenData,
  navigate?: (url: string) => void,
): RouteObject {
  if (!data) return { path, element }
  const load = typeof data === 'function' ? data : data.load
  const route: RouteObject = {
    path, element, loader: routeLoader(load, navigate), hydrateFallbackElement: element,
  }
  if (typeof data !== 'function') route.shouldRevalidate = data.shouldRevalidate
  return route
}

/**
 * Значение query так, как его читает СЕРВЕР: у Starlette при повторе
 * побеждает ПОСЛЕДНЕЕ, а `URLSearchParams.get` берёт первое. На адресе вида
 * `?date=A&date=B` страница после F5 и переход роутером показали бы разное.
 * Загрузчики читают query только так.
 */
export const queryParam = (q: URLSearchParams, name: string): string => q.getAll(name).at(-1) ?? ''

const LOADING = { status: 'loading' } as const

/**
 * Данные экрана из загрузчика маршрута — с тем же набором, что у `useLoad`:
 * повтор, подмена ответом POST и уход на вход при 401.
 */
export function useRouteLoad<T>(navigate: (url: string) => void = defaultNavigate) {
  /* `undefined` — роутер ещё рисует первый кадр (`hydrateFallbackElement`). */
  const data = useLoaderData() as LoadState<T> | undefined
  const { state: rv, revalidate } = useRevalidator()
  /* Своё состояние экрана поверх ответа загрузчика: подмена свежими данными
     после POST и «уходим». ⚠️ Живёт ровно до НОВОГО ответа загрузчика: иначе
     повтор принёс бы свежие данные, а экран показывал бы прежнюю подмену. */
  const [own, setOwn] = useState<LoadState<T> | null>(null)
  const [base, setBase] = useState(data)
  if (base !== data) {
    setBase(data)
    setOwn(null)
  }

  /* ⚠️ Во время повтора роутер держит ПРЕЖНИЕ данные (отказ) до ответа;
     экран же, как и с `useLoad`, обязан показать загрузку. */
  const state: LoadState<T> = rv === 'loading' || data === undefined ? LOADING : own ?? data
  /* Идёт переход роутером (другой адрес, новый ответ загрузчика ещё не пришёл).
     На экране пока ПРЕЖНИЕ данные; экран, которому их нельзя править в этот
     миг (осмотр пародонтограммы), сам решает показать загрузку. */
  const pending = useNavigation().state === 'loading'

  const retry = useCallback(() => { void revalidate() }, [revalidate])

  const replace = useCallback((d: T) => setOwn({ status: 'ready', data: d }), [])

  /** Отказ действия (POST): 401 уводит на вход, остальное — вызывающему. */
  const leaveIfSignedOut = useCallback((err: ApiError): boolean => {
    if (err.failure.kind !== 'unauthenticated') return false
    setOwn({ status: 'leaving' })
    navigate(loginUrl())
    return true
  }, [navigate])

  return { state, pending, retry, replace, leaveIfSignedOut }
}
