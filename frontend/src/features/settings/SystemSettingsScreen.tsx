import { useCallback, useState } from 'react'
import { Icon, iconName } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { t } from '../../utils/i18n'
import { settings, type SystemData } from './settings'

/* Подписи строк таблицы. Всё, что несёт ЗНАЧЕНИЕ (версия, состояние
   обновления, путь к папке, строка BitLocker, проза о приватности), приходит
   с сервера: это единственный экран, по которому директор сверяет, куда
   программа пишет, и описание раскладки, живущее здесь второй копией,
   протухло бы молча — так уже уехали клиникам семь фраз про «рядом с exe». */
const T = t('system', {
  title: 'Stare sistem',
  privacy: 'Confidențialitate',
  version: 'Versiune',
  db: 'Bază de date',
  folder: 'Folderul cu date',
  telegram: 'Canal Telegram',
  updates: 'Actualizări',
  channel: 'Canal actualizări',
  access: 'Acces jurnal',
  feedback: 'Feedback / suport',
  bitlocker: 'Criptare disc (BitLocker)',
  run: 'Actualizează acum',
  check: 'Verifică acum',
  uninstallStale: 'În «Programe și caracteristici» scrie versiunea',
  uninstallFix: 'Corectează (necesită drepturi de administrator)',
  uninstallWhy: 'Windows cere confirmare: intrarea aparține instalării, '
    + 'nu programului. Datele clinicii nu sunt atinse.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const)

interface Props {
  navigate?: (url: string) => void
}

/** Данные экрана грузит роутер (B2.2), App.tsx › LOADS. */
export const loadSystemSettings: RouteLoad<SystemData> = (signal) => settings.system(signal)

export function SystemSettingsScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<SystemData>(navigate)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [busy, setBusy] = useState(false)
  const closeToast = useCallback(() => setToast(null), [])

  /* «Verifică acum» у старой страницы была формой с редиректом на себя же:
     проверка синхронная, и человек видел результат на перезагруженной
     странице. Здесь тот же вызов отвечает СВЕЖЕЙ моделью, и строка обновления
     меняется на месте — второй запрос за ней не нужен. */
  async function check() {
    setBusy(true)
    try {
      const r = await settings.systemCheck()
      replace(r.data)
    } catch (e) {
      const err = asApiError(e)
      if (leaveIfSignedOut(err)) return
      setToast({ tone: 'err', text: err.text || T.offline })
    } finally {
      setBusy(false)
    }
  }

  /* ⛔ Окно UAC программа сама не показывает: правка записи установщика —
     косметика, а запрос прав на каждом старте перестают читать и начинают
     подтверждать не глядя. Кнопку нажимает человек, и нажимает там, где эту
     версию и видит. ⚠️ Ответ — свежая МОДЕЛЬ, а не «готово»: итог окна серверу
     не виден, и строка обновится, только если Windows действительно дала
     права. */
  async function fixUninstall() {
    setBusy(true)
    try {
      const r = await settings.uninstallSync()
      replace(r.data)
      if (r.code) setToast({ tone: r.tone, text: r.text })
    } catch (e) {
      const err = asApiError(e)
      if (leaveIfSignedOut(err)) return
      setToast({ tone: 'err', text: err.text || T.offline })
    } finally {
      setBusy(false)
    }
  }

  if (state.status === 'leaving') return null
  const head = <h2><Icon name="info" /> {T.title}</h2>

  if (state.status === 'failed') {
    return (
      <section className="dp-react-root">
        {head}
        <LoadFailed error={state.error} onRetry={retry} />
      </section>
    )
  }

  const data = state.status === 'ready' ? state.data : null
  const up = data?.update
  return (
    <section className="dp-react-root" aria-busy={data === null}>
      {head}
      {data && up && (
        <>
          <table className="set">
            <tbody>
              <tr>
                <th className="dp-set-th">{T.version}</th>
                <td>
                  v{data.version}
                  {data.uninstall.stale && (
                    /* ⭐ Строка появляется ТОЛЬКО когда расхождение есть: у
                       установки копированием записи нет вовсе, и предлагать
                       там «исправить» значило бы звать человека чинить то,
                       чего не существует. */
                    <div className="dp-hs-sub" style={{ marginTop: 6 }}>
                      <Icon name="excl" /> {T.uninstallStale} v{data.uninstall.version}.{' '}
                      <button
                        type="button"
                        className="savebtn"
                        disabled={busy}
                        onClick={fixUninstall}
                      >
                        {T.uninstallFix}
                      </button>
                      <br />
                      <span>{T.uninstallWhy}</span>
                    </div>
                  )}
                </td>
              </tr>
              <tr><th>{T.db}</th><td>{data.db}</td></tr>
              {data.folder.path && (
                <tr>
                  <th>{T.folder}</th>
                  <td>
                    {/* ⭐ Путь, а не «да/нет»: его сверяют глазами с адресной
                        строкой Проводника, и сокращение вроде «%ProgramData%»
                        сверить нельзя. */}
                    <code>{data.folder.path}</code>
                    <br />
                    <span className="dp-hs-sub">{data.folder.hint}</span>
                  </td>
                </tr>
              )}
              {data.telegram && (
                <tr>
                  <th>{T.telegram}</th>
                  <td dangerouslySetInnerHTML={{ __html: data.telegram }} />
                </tr>
              )}
              <tr>
                <th>{T.updates}</th>
                <td>
                  {up.icon && <><Icon name={iconName(up.icon)} /> </>}
                  {up.url ? (
                    <a href={up.url} target="_blank" rel="noreferrer">{up.text}</a>
                  ) : (
                    up.text
                  )}
                  {up.state === 'self' && (
                    /* ⛔ Запуск обновления остаётся ФОРМОЙ на старый маршрут:
                       он подменяет сам exe и отвечает целой страницей «se
                       actualizează…», которая обязана работать, когда
                       программа уже заменена под ногами. Через fetch её
                       пришлось бы переписать в React — то есть завести
                       второй экран ровно для той минуты, когда бандла может
                       не быть. */
                    <form method="post" action="/admin/update/run" className="dp-inline-form">
                      <button className="dp-upd-btn"><Icon name="upload" /> {T.run}</button>
                    </form>
                  )}
                  <button type="button" className="dp-check-btn" onClick={check} disabled={busy}>
                    <Icon name="refresh" /> {T.check}
                  </button>
                </td>
              </tr>
              {data.channel && (
                <tr>
                  <th>{T.channel}</th>
                  <td>
                    <b className="dp-tone-amber">{data.channel.name}</b> — {data.channel.warn}
                    {data.channel.note}
                  </td>
                </tr>
              )}
              <tr>
                <th>{T.access}</th>
                <td><Icon name={iconName(data.access.icon)} /> {data.access.text}</td>
              </tr>
              {data.bitlocker && (
                <tr>
                  <th>{T.bitlocker}</th>
                  <td className={data.bitlocker.tone === 'alarm' ? 'dp-bl-alarm'
                    : data.bitlocker.tone === 'warn' ? 'dp-tone-amber' : undefined}>
                    {data.bitlocker.icon && <><Icon name={iconName(data.bitlocker.icon)} /> </>}
                    {data.bitlocker.text}
                  </td>
                </tr>
              )}
              <tr>
                <th>{T.feedback}</th>
                <td><a href={`mailto:${data.feedback}`}>{data.feedback}</a></td>
              </tr>
            </tbody>
          </table>

          <h2><Icon name="shield" /> {T.privacy}</h2>
          <div className="pcard dp-measure" dangerouslySetInnerHTML={{ __html: data.privacy }} />
        </>
      )}
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
