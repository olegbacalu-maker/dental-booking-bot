import { useCallback, useState } from 'react'
import { ask } from '../../components/confirm'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { settings, type BackupCopy, type BackupData, type RestoreOrdered } from './settings'

/* Подписи. Всё, что несёт ЗНАЧЕНИЕ (даты копий, папка, отказы, что внутри
   принятой копии), приходит с сервера — описание расписания, живущее здесь
   второй копией, протухло бы молча.

   Экран переписан 17.10 вечером под регистратуру, не под IT (слово Олега:
   «слишком непонятно, слишком всё сложно»): наверху один выключатель, под
   ним куда и с какой паролью — одним предложением, строка-факт «Ultima
   copie», история копий ПО ДНЯМ, восстановление и ручной архив — сложены.
   Имена файлов, ротация, DPAPI — в FAQ, не здесь. */
const T = {
  title: 'Copie de rezervă',
  unavailable: 'Copia de rezervă există doar în ediția instalată pe calculatorul clinicii.',
  offline: 'Programul nu răspunde. Reîncercați.',

  daily: 'Copie zilnică automată',
  dailyOn: 'Programul face singur o copie a evidenței o dată pe zi, cât timp este pornit.',
  dailyOff: 'Oprită: rămâne doar copia făcută la pornirea programului.',
  last: 'Ultima copie:',
  never: 'încă nu s-a făcut',
  thisPc: 'pe acest calculator',

  whereHint: 'Ca să nu dispară odată cu calculatorul, copia se pune și într-un folder de pe alt disc, ' +
    'un stick USB lăsat în calculator sau folderul cloud al clinicii (OneDrive, Google Drive); ' +
    'parola o deschide pe orice calculator — notați-o.',
  folder: 'Folderul copiei (ex. D:\\Copii DentPilot sau E:\\)',
  pass: 'parola copiei (min. {n} caractere)',
  passKeep: 'parolă nouă — gol = rămâne cea salvată',
  passUnreadable: 'Parola salvată nu poate fi citită pe acest calculator (alt cont Windows sau ' +
    'Windows reinstalat) — introduceți-o din nou.',
  save: 'Salvează',
  runNow: 'Fă o copie acum',
  folderOff: 'Oprește copia din folder',

  history: 'Copiile făcute',
  histLocal: 'Pe acest calculator',
  histExt: 'În folderul ales',
  histNone: 'Încă nu există copii.',
  copies1: '1 copie',
  copiesN: '{n} copii',

  restoreTitle: 'Restaurare din copie',
  restoreHint: 'Înlocuiește evidența de acum cu o copie — la următoarea pornire, iar evidența de acum ' +
    'rămâne păstrată în folderul cu date.',
  pick: 'Copia',
  pickNone: '— alegeți copia —',
  pathLabel: 'Sau calea unei arhive de pe stick (ex. E:\\dentpilot-backup-20261017_0930.zip)',
  restorePass: 'parola arhivei',
  check: 'Verifică copia',
  staged: 'Copia verificată',
  patients: 'pacienți',
  appointments: 'programări',
  documents: 'documente',
  made: 'făcută la',
  clinic: 'clinica',
  confirm: 'Restaurează la următoarea pornire',
  confirmAsk: 'Evidența de acum va fi înlocuită cu copia „{name}" ({p} pacienți) la următoarea ' +
    'pornire. Evidența de acum rămâne în folderul cu date. Continuați?',
  cancel: 'Renunță',
  pending: 'Restaurarea este comandată și se face la următoarea pornire a programului.',
  pendingCancel: 'Anulează restaurarea',

  manualTitle: 'Copie manuală pe stick USB',
  manualHint: 'O arhivă cu toată evidența, pentru stick sau alt calculator. Parola nu se salvează ' +
    'nicăieri — fără ea arhiva nu poate fi deschisă de nimeni, nici de noi.',
  manualPass: 'parolă (min. {n} caractere)',
  export: 'Exportă arhiva',
} as const

/** Старый маршрут выгрузки: отдаёт файл, при отказе возвращает сюда с ?msg=. */
export const EXPORT_ACTION = '/admin/backup/export'

interface Props {
  navigate?: (url: string) => void
}

/** Данные экрана грузит роутер (B2.2), App.tsx › LOADS. */
export const loadBackupSettings: RouteLoad<BackupData> = (signal) => settings.backup(signal)

const fill = (s: string, n: number | string) => s.replace('{n}', String(n))

/** «2.9 MB», «24 MB»; меньше мегабайта — в KB: «0.0 MB» читалось бы как пустая копия. */
function size(bytes: number): string {
  const m = bytes / (1024 * 1024)
  if (m < 1) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return m >= 10 ? `${Math.round(m)} MB` : `${m.toFixed(1)} MB`
}

/** День → копии этого дня, в порядке сервера (новейшие вперёд). */
function byDay(items: BackupCopy[]): { day: string; items: BackupCopy[]; size: number }[] {
  const out: { day: string; items: BackupCopy[]; size: number }[] = []
  for (const c of items) {
    const last = out[out.length - 1]
    if (last && last.day === c.day) {
      last.items.push(c)
      last.size += c.size
    } else {
      out.push({ day: c.day, items: [c], size: c.size })
    }
  }
  return out
}

function History({ title, items }: { title: string; items: BackupCopy[] }) {
  if (items.length === 0) return null
  return (
    <div className="pcard dp-bk-hist">
      <b>{title}</b>
      <table>
        <tbody>
          {byDay(items).map((d) => (
            <tr key={d.day}>
              <td>{d.day}</td>
              <td>{d.items.length === 1 ? T.copies1 : T.copiesN.replace('{n}', String(d.items.length))}</td>
              <td className="dp-bk-size">{size(d.size)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Копии для выбора — одним списком по дням, не списком файлов. */
function PickList({ label, items, prefix }: { label: string; items: BackupCopy[]; prefix: 'local' | 'archive' }) {
  if (items.length === 0) return null
  return (
    <optgroup label={label}>
      {items.map((c) => (
        <option key={c.name} value={`${prefix}:${c.name}`}>{c.made}</option>
      ))}
    </optgroup>
  )
}

export function BackupSettingsScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<BackupData>(navigate)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [busy, setBusy] = useState(false)
  const [folder, setFolder] = useState<string | null>(null)
  const [autoPass, setAutoPass] = useState('')
  const [chosen, setChosen] = useState('')
  const [path, setPath] = useState('')
  const [rstPass, setRstPass] = useState('')
  const [ordered, setOrdered] = useState<RestoreOrdered | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

  function fail(e: unknown) {
    const err = asApiError(e)
    if (leaveIfSignedOut(err)) return
    setToast({ tone: 'err', text: err.text || T.offline })
  }

  async function call<R extends BackupData>(fn: () => Promise<{ data: R; code: string; text: string; tone: ToastState['tone'] }>,
    after?: (r: R) => void) {
    setBusy(true)
    try {
      const r = await fn()
      replace(r.data)
      if (r.code) setToast({ tone: r.tone, text: r.text })
      after?.(r.data)
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

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
  if (ordered?.text) {
    /* Программа закрывается и стартует заново — экран больше ничего не
       предлагает (как у выключения шифрования). */
    return (
      <section className="dp-react-root">
        {head}
        <div className="banner ok" role="status">
          <b>{ordered.text}</b>
          <br />
          <small>{ordered.note}</small>
        </div>
      </section>
    )
  }
  const data = state.status === 'ready' ? state.data : null
  const auto = data?.auto
  const rst = data?.restore
  const folderVal = folder ?? auto?.folder ?? ''
  const staged = rst?.staged ?? null

  async function saveFolder(off = false) {
    await call(() => settings.backupAuto({ folder: off ? '' : folderVal.trim(), password: off ? '' : autoPass }), () => {
      setFolder(null)
      setAutoPass('')
    })
  }

  async function stage() {
    const [kind, name] = chosen.split(':', 2) as ['local' | 'archive', string]
    const form = chosen
      ? (kind === 'local' ? { kind, name } : { kind, name, password: rstPass })
      : { kind: 'path' as const, path: path.trim(), password: rstPass }
    await call(() => settings.restoreStage(form), () => setRstPass(''))
  }

  async function orderRestore() {
    if (!staged) return
    const q = T.confirmAsk.replace('{name}', staged.name).replace('{p}', String(staged.patients))
    if (!await ask({ text: q, ok: T.confirm, danger: true })) return
    await call(() => settings.restoreConfirm(), (d) => { if (d.text) setOrdered(d) })
  }

  return (
    <section className="dp-react-root" aria-busy={data === null}>
      {head}
      {data && auto && rst && (
        <>
          {/* Янтарная строка — ТЕКСТ сервера, тот же, что в баннере директора и
              в Stare sistem (backup_loop.alert); выключенная копия молчит. */}
          {auto.alert && <div className="banner warn" role="status">{auto.alert}</div>}

          <div className="pcard dp-bk-top">
            <label className="dp-sw dp-bk-sw">
              <span>
                <b>{T.daily}</b>
                <br />
                <small className="dp-muted">{auto.enabled ? T.dailyOn : T.dailyOff}</small>
              </span>
              <input
                type="checkbox"
                role="switch"
                aria-checked={auto.enabled}
                aria-label={T.daily}
                checked={auto.enabled}
                disabled={busy}
                onChange={(e) => void call(() => settings.backupAuto({ enabled: e.target.checked }))}
              />
            </label>
            {/* ФАКТ: когда была последняя копия и куда — не описание расписания */}
            <p className="dp-bk-last">
              {T.last} <b>{auto.last.at || T.never}</b>
              {auto.last.at && <>, {auto.last.where ? `în ${auto.last.where}` : T.thisPc}</>}
            </p>

            {auto.enabled && (
              <>
                <p className="hint">{T.whereHint}</p>
                {auto.pass_unreadable && <div className="banner warn">{T.passUnreadable}</div>}
                <form className="add" onSubmit={(e) => { e.preventDefault(); void saveFolder() }}>
                  <input
                    type="text"
                    aria-label={T.folder}
                    placeholder={T.folder}
                    value={folderVal}
                    onChange={(e) => setFolder(e.target.value)}
                    style={{ width: 340 }}
                    disabled={busy}
                  />
                  <input
                    type="password"
                    aria-label={auto.has_pass ? T.passKeep : fill(T.pass, data.min_pass)}
                    placeholder={auto.has_pass ? T.passKeep : fill(T.pass, data.min_pass)}
                    value={autoPass}
                    onChange={(e) => setAutoPass(e.target.value)}
                    minLength={autoPass ? data.min_pass : 0}
                    style={{ width: 280 }}
                    autoComplete="new-password"
                    disabled={busy}
                  />
                  <button className="savebtn" disabled={busy || !folderVal.trim()}><Icon name="check" /> {T.save}</button>
                  {auto.folder && (
                    <>
                      <button type="button" className="dp-bk-q" onClick={() => void call(() => settings.backupRun())} disabled={busy}>
                        <Icon name="upload" /> {T.runNow}
                      </button>
                      <button type="button" className="dp-bk-q" onClick={() => void saveFolder(true)} disabled={busy}>
                        {T.folderOff}
                      </button>
                    </>
                  )}
                </form>
              </>
            )}
          </div>

          <h3>{T.history}</h3>
          {rst.local.length === 0 && rst.archives.length === 0
            ? <p className="hint">{T.histNone}</p>
            : (
              <div className="dp-bk-hists">
                <History title={T.histLocal} items={rst.local} />
                <History title={T.histExt} items={rst.archives} />
              </div>
            )}

          <details className="pcard dp-fold dp-bk-fold">
            <summary><Icon name="refresh" /> <b>{T.restoreTitle}</b>
              <span className="dp-fold-c" aria-hidden="true"><Icon name="chev-r" /></span>
            </summary>
            <p className="hint">{T.restoreHint}</p>
            {rst.pending ? (
              <div className="banner warn" role="status">
                {T.pending}{' '}
                <button type="button" className="rowdel" onClick={() => void call(() => settings.restoreCancel())} disabled={busy}>
                  {T.pendingCancel}
                </button>
              </div>
            ) : staged ? (
              <div className="pcard" role="status">
                <b>{T.staged}:</b> {staged.made || staged.name}
                <br />
                {/* Что ВНУТРИ — до подтверждения: число пациентов есть ответ на
                    «это точно та копия?», и он виден раньше кнопки. */}
                <b>{staged.patients}</b> {T.patients} · <b>{staged.appointments}</b> {T.appointments} ·{' '}
                <b>{staged.documents}</b> {T.documents}
                {staged.made && <> · {T.made} {staged.made}</>}
                {staged.clinic && <> · {T.clinic} {staged.clinic}</>}
                <div className="nav" style={{ marginTop: 8 }}>
                  <button type="button" className="savebtn" onClick={() => void orderRestore()} disabled={busy}>
                    <Icon name="check" /> {T.confirm}
                  </button>
                  <button type="button" className="rowdel" onClick={() => void call(() => settings.restoreCancel())} disabled={busy}>
                    {T.cancel}
                  </button>
                </div>
              </div>
            ) : (
              <form className="add" onSubmit={(e) => { e.preventDefault(); void stage() }}>
                {(rst.local.length > 0 || rst.archives.length > 0) && (
                  <select
                    aria-label={T.pick}
                    value={chosen}
                    onChange={(e) => { setChosen(e.target.value); if (e.target.value) setPath('') }}
                    disabled={busy}
                  >
                    <option value="">{T.pickNone}</option>
                    <PickList label={T.histLocal} items={rst.local} prefix="local" />
                    <PickList label={T.histExt} items={rst.archives} prefix="archive" />
                  </select>
                )}
                <input
                  type="text"
                  aria-label={T.pathLabel}
                  placeholder={T.pathLabel}
                  value={path}
                  onChange={(e) => { setPath(e.target.value); setChosen('') }}
                  style={{ width: 420 }}
                  disabled={busy}
                />
                {!chosen.startsWith('local:') && (
                  <input
                    type="password"
                    aria-label={T.restorePass}
                    placeholder={T.restorePass}
                    value={rstPass}
                    onChange={(e) => setRstPass(e.target.value)}
                    style={{ width: 220 }}
                    autoComplete="off"
                    disabled={busy}
                  />
                )}
                <button className="savebtn" disabled={busy || (!chosen && !path.trim())}>
                  <Icon name="eye" /> {T.check}
                </button>
              </form>
            )}
          </details>

          <details className="pcard dp-fold dp-bk-fold">
            <summary><Icon name="download" /> <b>{T.manualTitle}</b>
              <span className="dp-fold-c" aria-hidden="true"><Icon name="chev-r" /></span>
            </summary>
            <p className="hint">{T.manualHint}</p>
            {/* Сама выгрузка идёт ОБЫЧНОЙ формой на старый маршрут: файл может
                весить сотни мегабайт, браузер качает ответ формы потоком. */}
            <form className="add" method="post" action={EXPORT_ACTION}>
              <input
                type="password"
                name="parola"
                placeholder={fill(T.manualPass, data.min_pass)}
                aria-label={fill(T.manualPass, data.min_pass)}
                minLength={data.min_pass}
                required
                style={{ width: 280 }}
                autoComplete="new-password"
              />
              <button><Icon name="download" /> {T.export}</button>
            </form>
          </details>
        </>
      )}
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
