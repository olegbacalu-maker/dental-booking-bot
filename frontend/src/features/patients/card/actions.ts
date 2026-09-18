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
}
