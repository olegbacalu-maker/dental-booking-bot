import { useCallback } from 'react'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { settings } from './settings'

const T = {
  title: 'Copie de rezervă criptată',
  password: 'parolă (min. {n} caractere)',
  export: 'Exportă arhiva',
  hintA: 'Arhivă ZIP criptată (AES-256) cu baza de date, profilul clinicii și documentele ' +
    'pacienților — pentru stick USB sau alt calculator. Se deschide cu 7-Zip prin parola aleasă. ',
  hintB: 'Parola nu se salvează nicăieri',
  hintC: ' — fără ea arhiva nu poate fi citită de nimeni, nici de noi.',
  unavailable: 'Copia de rezervă există doar în ediția instalată pe calculatorul clinicii.',
} as const

/** Старый маршрут выгрузки: отдаёт файл, при отказе возвращает сюда с ?msg=. */
export const EXPORT_ACTION = '/admin/backup/export'

interface Props {
  navigate?: (url: string) => void
}

/**
 * Экспорт архива. Сама выгрузка идёт ОБЫЧНОЙ формой на старый маршрут: файл
 * может весить сотни мегабайт, а браузер скачивает ответ формы потоком и
 * показывает ход загрузки; читать архив в память через fetch ради «React»
 * значило бы сделать хуже. Отказ (короткая парола, снимок не собрался)
 * сервер возвращает редиректом на эту страницу с ?msg=, и плашку рисует рамка.
 */
export function BackupSettingsScreen({ navigate = defaultNavigate }: Props) {
  const load = useCallback((signal: AbortSignal) => settings.backup(signal), [])
  const { state, retry } = useLoad(load, navigate)

  if (state.status === 'leaving') return null
  const head = <h2><Icon name="save" /> {T.title}</h2>
  if (state.status === 'failed') {
    const gone = state.error.failure.kind === 'server' && state.error.failure.status === 404
    return (
      <section className="dp-react-root">
        {head}
        <LoadFailed error={state.error} onRetry={retry} {...(gone ? { text: T.unavailable } : {})} />
      </section>
    )
  }
  const data = state.status === 'ready' ? state.data : null
  return (
    <section className="dp-react-root" aria-busy={data === null}>
      {head}
      <form className="add" method="post" action={EXPORT_ACTION}>
        <input
          type="password"
          name="parola"
          placeholder={T.password.replace('{n}', String(data?.min_pass ?? ''))}
          aria-label={T.password.replace('{n}', String(data?.min_pass ?? ''))}
          minLength={data?.min_pass ?? 1}
          required
          style={{ width: 280 }}
          autoComplete="new-password"
          disabled={data === null}
        />
        <button disabled={data === null}><Icon name="download" /> {T.export}</button>
      </form>
      <p className="hint">{T.hintA}<b>{T.hintB}</b>{T.hintC}</p>
    </section>
  )
}
