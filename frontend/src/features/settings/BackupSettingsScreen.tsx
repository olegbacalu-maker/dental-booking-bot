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
   второй копией, протухло бы молча. */
const T = {
  title: 'Copie de rezervă criptată',
  password: 'parolă (min. {n} caractere)',
  export: 'Exportă arhiva',
  hintA: 'Arhivă ZIP criptată (AES-256) cu baza de date, profilul clinicii și documentele ' +
    'pacienților — pentru stick USB sau alt calculator. Se deschide cu 7-Zip prin parola aleasă. ',
  hintB: 'Parola nu se salvează nicăieri',
  hintC: ' — fără ea arhiva nu poate fi citită de nimeni, nici de noi.',
  unavailable: 'Copia de rezervă există doar în ediția instalată pe calculatorul clinicii.',

  autoTitle: 'Copie automată în afara calculatorului',
  autoHint: 'O dată pe zi, cât timp programul este pornit, se pune în folderul ales o arhivă ' +
    'la fel ca cea de mai sus (ultimele {k} se păstrează). Alegeți un folder de pe alt disc, ' +
    'un stick USB lăsat în calculator sau folderul cloud al clinicii (OneDrive, Google Drive). ' +
    'Copia zilnică de pe acest calculator (data\\backups) se face oricum.',
  folder: 'Folderul copiei (ex. D:\\Copii DentPilot sau E:\\)',
  autoPass: 'parola arhivelor (min. {n} caractere)',
  autoPassKeep: 'parolă nouă — gol = rămâne cea salvată',
  passUnreadable: 'Parola salvată nu poate fi citită pe acest calculator (alt cont Windows sau ' +
    'Windows reinstalat) — introduceți-o din nou.',
  save: 'Salvează',
  runNow: 'Fă o copie acum',
  off: 'Oprește copia automată',
  lastLocal: 'Copia zilnică de pe acest calculator:',
  lastExt: 'Ultima copie externă:',
  never: 'încă nu s-a făcut',

  restoreTitle: 'Restaurează din copie',
  restoreHint: 'Alegeți o copie, programul verifică ce este înăuntru și vă arată câți pacienți ' +
    'conține. Înlocuirea se face la următoarea pornire, de către program, niciodată cu ' +
    'evidența deschisă. Baza de acum NU se șterge: rămâne în folderul cu date sub numele ' +
    'dental.before-restore-<data>.db.',
  localList: 'Copii zilnice de pe acest calculator',
  archiveList: 'Arhive din folderul copiei automate',
  pathLabel: 'Sau calea unei arhive (ex. E:\\dentpilot-backup-20261017_0930.zip)',
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
    'pornire. Baza de acum rămâne în folderul cu date. Continuați?',
  cancel: 'Renunță',
  pending: 'Restaurarea este comandată și se face la următoarea pornire a programului.',
  pendingCancel: 'Anulează restaurarea',
  offline: 'Programul nu răspunde. Reîncercați.',
} as const

/** Старый маршрут выгрузки: отдаёт файл, при отказе возвращает сюда с ?msg=. */
export const EXPORT_ACTION = '/admin/backup/export'

interface Props {
  navigate?: (url: string) => void
}

/** Данные экрана грузит роутер (B2.2), App.tsx › LOADS. */
export const loadBackupSettings: RouteLoad<BackupData> = (signal) => settings.backup(signal)

const fill = (s: string, n: number | string) => s.replace('{n}', String(n))

function CopyList({ title, items, prefix, chosen, onPick }: {
  title: string
  items: BackupCopy[]
  prefix: 'local' | 'archive'
  chosen: string
  onPick: (v: string) => void
}) {
  if (items.length === 0) return null
  return (
    <div className="pcard" style={{ marginBottom: 10 }}>
      <b>{title}</b>
      {items.map((c) => {
        const v = `${prefix}:${c.name}`
        return (
          <label key={v} style={{ display: 'block', marginTop: 4 }}>
            <input type="radio" name="rst" value={v} checked={chosen === v} onChange={() => onPick(v)} />
            {' '}{c.made} — <code>{c.name}</code>
          </label>
        )
      })}
    </div>
  )
}

/**
 * Три части одного экрана (17.10): ручной экспорт, внешняя копия по
 * расписанию, восстановление. Сама выгрузка идёт ОБЫЧНОЙ формой на старый
 * маршрут: файл может весить сотни мегабайт, браузер качает ответ формы
 * потоком; остальное — JSON API, и каждый ответ несёт всю модель экрана.
 */
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

  async function saveAuto(off = false) {
    await call(() => settings.backupAuto(off ? '' : folderVal.trim(), off ? '' : autoPass), () => {
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
      <form className="add" method="post" action={EXPORT_ACTION}>
        <input
          type="password"
          name="parola"
          placeholder={fill(T.password, data?.min_pass ?? '')}
          aria-label={fill(T.password, data?.min_pass ?? '')}
          minLength={data?.min_pass ?? 1}
          required
          style={{ width: 280 }}
          autoComplete="new-password"
          disabled={data === null}
        />
        <button disabled={data === null}><Icon name="download" /> {T.export}</button>
      </form>
      <p className="hint">{T.hintA}<b>{T.hintB}</b>{T.hintC}</p>

      {data && auto && rst && (
        <>
          <h2><Icon name="folder" /> {T.autoTitle}</h2>
          <p className="hint">{fill(T.autoHint.replace('{k}', String(auto.keep)), data.min_pass)}</p>
          <div className={auto.alert ? 'banner warn' : 'pcard'} style={{ marginBottom: 10 }}>
            {/* ФАКТЫ: когда были копии; описание расписания — в подсказке выше */}
            {T.lastLocal} <b>{auto.local_at || T.never}</b>
            {auto.local_error && <> — {auto.local_error}</>}
            <br />
            {T.lastExt} <b>{auto.folder ? (auto.ext_at || T.never) : '—'}</b>
            {auto.ext_error && <> — {auto.ext_error}</>}
          </div>
          {auto.pass_unreadable && <div className="banner warn">{T.passUnreadable}</div>}
          <form className="add" onSubmit={(e) => { e.preventDefault(); void saveAuto() }}>
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
              aria-label={auto.has_pass ? T.autoPassKeep : fill(T.autoPass, data.min_pass)}
              placeholder={auto.has_pass ? T.autoPassKeep : fill(T.autoPass, data.min_pass)}
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
                <button type="button" onClick={() => void call(() => settings.backupRun())} disabled={busy}>
                  <Icon name="upload" /> {T.runNow}
                </button>
                <button type="button" className="rowdel" onClick={() => void saveAuto(true)} disabled={busy}>
                  {T.off}
                </button>
              </>
            )}
          </form>

          <h2><Icon name="refresh" /> {T.restoreTitle}</h2>
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
              <b>{T.staged}:</b> <code>{staged.name}</code>
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
              <CopyList title={T.localList} items={rst.local} prefix="local" chosen={chosen} onPick={setChosen} />
              <CopyList title={T.archiveList} items={rst.archives} prefix="archive" chosen={chosen} onPick={setChosen} />
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
        </>
      )}
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
