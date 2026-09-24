import { useCallback } from 'react'
import { useLoaderData, useRevalidator, type LoaderFunctionArgs } from 'react-router'
import { asApiError, loginUrl, type ApiResult } from '../services/api'
import { defaultNavigate, type LoadState } from './useLoad'

/**
 * Загрузка данных экрана РОУТЕРОМ (B2.2) — тот же цикл, что у `useLoad`, но
 * запрос уходит в момент выбора маршрута, а не после первой отрисовки.
 *
 * ⭐ Загрузчик отдаёт ту же `LoadState`, что и `useLoad`, и НЕ бросает на
 * отказе сервера: брошенное ушло бы в ловушку ошибок маршрута, и экран
 * потерял бы свою плашку отказа с повтором и ссылкой на старую страницу.
 * Бросает он только то, чего не ждёт никто, — это и есть работа ловушки.
 *
 * ⚠️ Маршрут с загрузчиком ОБЯЗАН нести `hydrateFallbackElement`: без него
 * роутер на первом кадре рисует вместо КОРНЯ `null`, и вместе с экраном
 * пропадает оболочка — мигание, которое убирал B1. Стенд — scripts/loader_hold.py.
 */
export function routeLoader<T>(
  load: (signal: AbortSignal) => Promise<ApiResult<T>>,
  navigate: (url: string) => void = defaultNavigate,
) {
  return async ({ request }: LoaderFunctionArgs): Promise<LoadState<T>> => {
    try {
      const r = await load(request.signal)
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

/** Данные экрана из загрузчика маршрута и повтор — перезапуск того же загрузчика. */
export function useRouteLoad<T>() {
  const data = useLoaderData() as LoadState<T>
  const { state: rv, revalidate } = useRevalidator()
  // ⚠️ Во время повтора роутер держит ПРЕЖНИЕ данные (отказ) до ответа;
  // экран же, как и с `useLoad`, обязан показать загрузку, а не старый отказ.
  const state: LoadState<T> = rv === 'loading' ? { status: 'loading' } : data
  const retry = useCallback(() => { void revalidate() }, [revalidate])
  return { state, retry }
}
