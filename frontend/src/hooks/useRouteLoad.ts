import { useCallback, useState, type ReactElement } from 'react'
import {
  useLoaderData, useRevalidator, type LoaderFunctionArgs, type Params, type RouteObject,
} from 'react-router'
import { asApiError, loginUrl, type ApiResult } from '../services/api'
import type { ApiError } from '../types/api'
import { defaultNavigate, type LoadState } from './useLoad'

/**
 * Загрузка данных экрана РОУТЕРОМ (B2.2) — тот же цикл, что у `useLoad`, но
 * запрос уходит в момент выбора маршрута, а не после первой отрисовки.
 */

/** Что экран просит у движка: сигнал отмены роутера и параметры ПУТИ. */
export type RouteLoad<T> = (signal: AbortSignal, params: Params) => Promise<ApiResult<T>>

/**
 * ⭐ Загрузчик отдаёт ту же `LoadState`, что и `useLoad`, и НЕ бросает на
 * отказе сервера: брошенное ушло бы в ловушку ошибок маршрута, и экран
 * потерял бы свою плашку отказа с повтором и ссылкой на старую страницу.
 * Бросает он только то, чего не ждёт никто, — это и есть работа ловушки.
 */
export function routeLoader<T>(load: RouteLoad<T>, navigate: (url: string) => void = defaultNavigate) {
  return async ({ request, params }: LoaderFunctionArgs): Promise<LoadState<T>> => {
    try {
      const r = await load(request.signal, params)
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
  path: string, element: ReactElement, load?: RouteLoad<unknown>,
  navigate?: (url: string) => void,
): RouteObject {
  if (!load) return { path, element }
  return { path, element, loader: routeLoader(load, navigate), hydrateFallbackElement: element }
}

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

  const retry = useCallback(() => { void revalidate() }, [revalidate])

  const replace = useCallback((d: T) => setOwn({ status: 'ready', data: d }), [])

  /** Отказ действия (POST): 401 уводит на вход, остальное — вызывающему. */
  const leaveIfSignedOut = useCallback((err: ApiError): boolean => {
    if (err.failure.kind !== 'unauthenticated') return false
    setOwn({ status: 'leaving' })
    navigate(loginUrl())
    return true
  }, [navigate])

  return { state, retry, replace, leaveIfSignedOut }
}
