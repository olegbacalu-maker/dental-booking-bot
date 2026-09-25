import { Icon } from './Icon'
import { AppLink } from '../components/AppLink'
import { legacyUrl } from '../utils/legacy'
import type { ApiError } from '../types/api'

/*
 * Общие для всех экранов подписи отказа загрузки: текст сервера, если он
 * был, иначе единственная своя фраза — движок не ответил.
 */
const T = {
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
  retry: 'Reîncearcă',
  legacy: 'Varianta clasică',
} as const

interface Props {
  error: ApiError
  onRetry: () => void
  /** Свой текст вместо серверного/общего (например, «врача нет»). */
  text?: string
}

/** Экран не загрузился: причина, повтор (кроме отказа в праве) и путь на старую страницу. */
export function LoadFailed({ error, onRetry, text }: Props) {
  const retryable = error.failure.kind !== 'forbidden'
  return (
    <>
      <div className="banner err" role="alert">{text || error.text || T.offline}</div>
      <p className="dp-actions">
        {retryable && (
          <button type="button" className="savebtn" onClick={onRetry}>
            <Icon name="refresh" /> {T.retry}
          </button>
        )}
        <AppLink href={legacyUrl()}>{T.legacy}</AppLink>
      </p>
    </>
  )
}
