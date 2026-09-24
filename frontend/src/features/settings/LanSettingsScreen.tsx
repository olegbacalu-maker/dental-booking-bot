import { useCallback, useState } from 'react'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { settings, type LanData, type LanSaved } from './settings'

/* Проза страницы (что это, предупреждение о второй установке, советы)
   приходит с сервера теми же кусками, что у старой страницы. Здесь только
   подписи кнопок. */
const T = {
  title: 'Acces din rețea',
  on: 'Activează accesul',
  off: 'Dezactivează accesul',
  confirm: 'Programul se va reporni pentru aplicare. Continuați?',
  firewall: 'Creează regula de firewall',
  unavailable: 'Secțiunea există doar în ediția instalată pe calculatorul clinicii.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

interface Props {
  navigate?: (url: string) => void
}

/** Данные экрана грузит роутер (B2.2), App.tsx › LOADS. */
export const loadLanSettings: RouteLoad<LanData> = (signal) => settings.lan(signal)

export function LanSettingsScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, leaveIfSignedOut } = useRouteLoad<LanData>(navigate)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState<LanSaved | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

  function fail(e: unknown) {
    const err = asApiError(e)
    if (leaveIfSignedOut(err)) return
    setToast({ tone: 'err', text: err.text || T.offline })
  }

  async function toggle(mode: 'on' | 'off') {
    if (!window.confirm(T.confirm)) return
    setBusy(true)
    try {
      const r = await settings.lanSave(mode)
      setToast({ tone: r.tone, text: r.text })
      if (r.data.text) setSaved(r.data)
      else retry()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  async function firewall() {
    setBusy(true)
    try {
      await settings.lanFirewall()
      retry()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  if (state.status === 'leaving') return null
  const head = <h2><Icon name="wifi" /> {T.title}</h2>

  if (state.status === 'failed') {
    const gone = state.error.failure.kind === 'server' && state.error.failure.status === 404
    return (
      <section className="dp-react-root">
        {head}
        <LoadFailed error={state.error} onRetry={retry} {...(gone ? { text: T.unavailable } : {})} />
      </section>
    )
  }

  if (saved) {
    // Программа закрывается и стартует заново — страница больше ничего не
    // предлагает: следующий запрос уже ушёл бы в пустоту.
    return (
      <section className="dp-react-root">
        {head}
        <div className="banner ok" role="status">
          <b>{saved.text}</b>
          <br />
          <small>{saved.note}</small>
        </div>
      </section>
    )
  }

  const data = state.status === 'ready' ? state.data : null
  return (
    <section className="dp-react-root" aria-busy={data === null}>
      {head}
      {data && (
        <>
          <div dangerouslySetInnerHTML={{ __html: data.blocks.intro }} />
          <div dangerouslySetInnerHTML={{ __html: data.blocks.status }} />
          {data.blocks.firewall && (
            <>
              <div dangerouslySetInnerHTML={{ __html: data.blocks.firewall }} />
              <button type="button" className="dp-fw-btn" onClick={firewall} disabled={busy}>
                <Icon name="shield" /> {T.firewall}
              </button>
            </>
          )}
          {data.blocks.tips && <div dangerouslySetInnerHTML={{ __html: data.blocks.tips }} />}
          <button
            type="button"
            className={data.enabled ? 'dp-lan-btn off' : 'dp-lan-btn on'}
            onClick={() => toggle(data.enabled ? 'off' : 'on')}
            disabled={busy}
          >
            {data.enabled ? T.off : T.on}
          </button>
        </>
      )}
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
