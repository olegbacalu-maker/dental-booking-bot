import { useEffect } from 'react'
import type { ApiResult } from '../../../services/api'
import type { ApiError } from '../../../types/api'
import type { PatientCard } from './card'

/**
 * Что карточки фиши получают от экрана: чью фишу правят, в каком режиме
 * ленты, и одну функцию `act`. Удача действия подменяет фишу целиком и
 * показывает плашку сервера; отказ показывает плашку и ВОЗВРАЩАЕТ ошибку —
 * форма по `error.field` подсвечивает виновное поле. 401 уводит на вход
 * внутри `act`, вызывающему возвращается та же ошибка.
 */
export interface CardActions {
  pid: number
  views: boolean
  busy: boolean
  act: (run: () => Promise<ApiResult<PatientCard>>) => Promise<ApiError | null>
  /** Адрес фиши с ТЕКУЩЕЙ вкладкой — «назад» на печатных листах (`print.ts`). */
  back: string
  /** Короткая форма карточки тронута / снова пуста (`useFormTouched`): её
   *  состояние живёт в карточке и умирает со сменой вкладки, поэтому о нём
   *  знает блокер ухода фиши. */
  form?: ((k: FormKey, on: boolean) => void) | undefined
}

/** Короткие формы фиши, о которых спрашивают при уходе, — в порядке вопроса. */
export const FORM_KEYS = ['profile', 'plan', 'pay', 'alert', 'doc'] as const
export type FormKey = (typeof FORM_KEYS)[number]

/** Сообщить экрану, тронута ли форма; снятие карточки — «не тронута». */
export function useFormTouched(a: CardActions, k: FormKey, on: boolean): void {
  const report = a.form
  useEffect(() => { report?.(k, on) }, [report, k, on])
  useEffect(() => () => report?.(k, false), [report, k])
}
