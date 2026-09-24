import { useCallback, useState } from 'react'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { t } from '../../utils/i18n'
import { settings, type CryptData, type CryptStopped } from './settings'

/* Проза раздела (что делает, чего стоит, чего НЕ делает) приходит с сервера
   теми же кусками, что рисует старая страница: текст, объясняющий директору,
   чем он рискует, обязан быть ОДНИМ. Здесь только подписи кнопок. */
const T = t('crypt', {
  title: 'Criptarea evidenței',
  prepare: 'Pregătește criptarea ›',
  sheet: 'Foaia de recuperare',
  sheetOpen: 'Deschide foaia de recuperare',
  stop: 'Oprește criptarea',
  confirm: 'Evidența va fi decriptată la următoarea pornire. Continuați?',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const)

interface Props {
  navigate?: (url: string) => void
}

/** Данные экрана грузит роутер (B2.2), App.tsx › LOADS. */
export const loadCryptSettings: RouteLoad<CryptData> = (signal) => settings.crypt(signal)

export function CryptSettingsScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, leaveIfSignedOut } = useRouteLoad<CryptData>(navigate)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [busy, setBusy] = useState(false)
  const [stopped, setStopped] = useState<CryptStopped | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

  function fail(e: unknown) {
    const err = asApiError(e)
    if (leaveIfSignedOut(err)) return
    /* ⚠️ Тон отказа здесь ВСЕГДА красный, как у всех экранов: конверт
       несёт `tone`, но `ApiError` его не хранит, и чинить это на одном
       экране нельзя — правка транспорта задевает все сорок. Единственный
       отказ этого раздела с тоном `warn` — `crypt_on` у устаревшей
       вкладки; записан строкой в tasks.md. */
    setToast({ tone: 'err', text: err.text || T.offline })
  }

  /* Подготовка ведёт на ПЕЧАТНЫЙ лист — серверную страницу, и это не
     недоделка переноса: без кода с этой бумаги база не откроется никогда
     после смены ПК, поэтому она обязана открываться и тогда, когда бандл не
     загрузился. Адрес листа приходит от сервера, а не склеивается здесь:
     адрес принадлежит тому, кто его обслуживает. */
  async function prepare() {
    setBusy(true)
    try {
      const r = await settings.cryptPrepare()
      navigate(r.data.sheet)
    } catch (e) {
      fail(e)
      setBusy(false)
    }
  }

  async function stop() {
    if (!window.confirm(T.confirm)) return
    setBusy(true)
    try {
      const r = await settings.cryptStop()
      setToast({ tone: r.tone, text: r.text })
      if (r.data.text) setStopped(r.data)
      else retry()
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  if (state.status === 'leaving') return null
  const head = <h2><Icon name="lock" /> {T.title}</h2>

  if (state.status === 'failed') {
    return (
      <section className="dp-react-root">
        {head}
        <LoadFailed error={state.error} onRetry={retry} />
      </section>
    )
  }

  if (stopped) {
    /* Программа закрывается и стартует заново — раздел больше ничего не
       предлагает: следующий запрос ушёл бы в пустоту. */
    return (
      <section className="dp-react-root">
        {head}
        <div className="banner ok" role="status">
          <b>{stopped.text}</b>
          <br />
          <small>{stopped.note}</small>
        </div>
      </section>
    )
  }

  const data = state.status === 'ready' ? state.data : null
  /* ⛔ У облачного издания заголовка нет: файла базы там не существует, и
     раздела тоже — есть только объяснение, почему его нет. Так же ведёт себя
     старая страница. */
  if (data && data.state === 'cloud') {
    return (
      <section className="dp-react-root">
        <div dangerouslySetInnerHTML={{ __html: data.blocks.status }} />
      </section>
    )
  }

  return (
    <section className="dp-react-root" aria-busy={data === null}>
      {head}
      {data && (
        <>
          <div dangerouslySetInnerHTML={{ __html: data.blocks.status }} />
          {data.blocks.note && <div dangerouslySetInnerHTML={{ __html: data.blocks.note }} />}
          {data.blocks.what && <div dangerouslySetInnerHTML={{ __html: data.blocks.what }} />}
          {data.blocks.cost && <div dangerouslySetInnerHTML={{ __html: data.blocks.cost }} />}
          {data.blocks.limit && <div dangerouslySetInnerHTML={{ __html: data.blocks.limit }} />}
          {data.state !== 'off' && (
            <div className="nav">
              <a className={data.state === 'pending' ? 'primary' : undefined} href={data.sheet}>
                <Icon name="print" /> {data.state === 'pending' ? T.sheetOpen : T.sheet}
              </a>
            </div>
          )}
          {data.state === 'on' && (
            <button type="button" className="rowdel" onClick={stop} disabled={busy}>
              {T.stop}
            </button>
          )}
          {data.state === 'off' && (
            <button type="button" className="savebtn" onClick={prepare} disabled={busy}>
              {T.prepare}
            </button>
          )}
        </>
      )}
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
