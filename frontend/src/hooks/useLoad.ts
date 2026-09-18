import { useCallback, useEffect, useState } from 'react'
import { asApiError, loginUrl, type ApiResult } from '../services/api'
import type { ApiError } from '../types/api'

/**
 * Загрузка данных экрана — один цикл на все экраны: загрузка, готово, отказ,
 * и «уходим на вход» при 401. Повтор перезапускает загрузку; `replace`
 * подменяет данные тем, что вернул удачный POST (ответы движка несут свежую
 * фишу), чтобы не ходить за ними второй раз.
 */
export type LoadState<T> =
  | { status: 'loading' }
  | { status: 'ready'; data: T }
  | { status: 'failed'; error: ApiError }
  /* 401: браузер уже уходит на вход; форму не показывать даже кадр. */
  | { status: 'leaving' }

/* Вне хука, чтобы ссылка была стабильной: иначе эффект перезапускался бы на
   каждый рендер. Подменяется в тестах: jsdom не умеет переходов. */
export const defaultNavigate = (url: string) => window.location.assign(url)

export function useLoad<T>(
  load: (signal: AbortSignal) => Promise<ApiResult<T>>,
  navigate: (url: string) => void = defaultNavigate,
) {
  const [state, setState] = useState<LoadState<T>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const ctl = new AbortController()
    load(ctl.signal).then(
      (r) => setState({ status: 'ready', data: r.data }),
      (e: unknown) => {
        if (ctl.signal.aborted) return
        const err = asApiError(e)
        if (err.failure.kind === 'unauthenticated') {
          setState({ status: 'leaving' })
          navigate(loginUrl())
          return
        }
        setState({ status: 'failed', error: err })
      },
    )
    return () => ctl.abort()
  }, [load, navigate, attempt])

  const retry = useCallback(() => {
    setState({ status: 'loading' })
    setAttempt((n) => n + 1)
  }, [])

  /**
   * Вернуть экран в «загрузку» перед сменой того, ЧТО грузится (другой
   * осмотр, другой период). Без этого прежние данные висят на экране весь
   * запрос: человек уже выбрал другое, а видит и ПРАВИТ старое — и правка
   * уходит в запись, которую он только что покинул. `retry` для этого не
   * годится: он перезапускает ту же загрузку.
   */
  const reset = useCallback(() => setState({ status: 'loading' }), [])

  const replace = useCallback((data: T) => setState({ status: 'ready', data }), [])

  /** Отказ действия (POST): 401 уводит на вход, остальное — вызывающему. */
  const leaveIfSignedOut = useCallback(
    (err: ApiError): boolean => {
      if (err.failure.kind !== 'unauthenticated') return false
      setState({ status: 'leaving' })
      navigate(loginUrl())
      return true
    },
    [navigate],
  )

  return { state, retry, reset, replace, leaveIfSignedOut }
}
