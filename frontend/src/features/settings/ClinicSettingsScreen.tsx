import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { Toast, type ToastState } from '../../components/Toast'
import { loginUrl } from '../../services/api'
import { ApiError } from '../../types/api'
import { clinicSettings, type ClinicForm, type ClinicSettings } from './clinicSettings'

/*
 * Подписи ЭТОГО экрана живут здесь — как у старой страницы они жили в её
 * обработчике (settings/routes.py). Общее — коды и тексты ответов, названия
 * статусов — серверное и приходит в конверте; клиент их не переводит и не
 * дублирует. Слова те же, что на старой странице: регистратура обучена на ней.
 */
const T = {
  title: 'Clinica',
  name: 'Nume',
  phone: 'Telefon',
  addrRo: 'Adresa (RO)',
  addrRu: 'Adresa (RU)',
  save: 'Salvează',
  hintA: 'Numele, telefonul și adresa apar în bot (',
  hintB:
    'contacte), în bara laterală a registrului și pe documentele tipărite ' +
    '(043/e, acord, raport de casă). Restul secțiunilor nu sunt atinse la salvare.',
  /* Единственный текст, которого сервер дать не может: его самого не было. */
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
  retry: 'Reîncearcă',
  legacy: 'Varianta clasică',
} as const

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; data: ClinicSettings }
  | { status: 'failed'; error: ApiError }
  /* 401: браузер уже уходит на вход; форму не показывать даже кадр. */
  | { status: 'leaving' }

const EMPTY: ClinicForm = { name: '', phone: '', address: { ro: '', ru: '' } }

function toForm(d: ClinicSettings): ClinicForm {
  return { name: d.name, phone: d.phone, address: { ro: d.address.ro, ru: d.address.ru } }
}

function asApiError(e: unknown): ApiError {
  return e instanceof ApiError
    ? e
    : new ApiError({ kind: 'network', detail: String(e) }, String(e))
}

/** Старая страница того же экрана — откат на один запрос, без сборки. */
export function legacyUrl(): string {
  return `${window.location.pathname}?ui=legacy`
}

/* Вне компонента, чтобы ссылка была стабильной: параметр по умолчанию,
   созданный в теле, был бы новой функцией на каждый рендер и перезапускал
   бы эффект загрузки без конца. */
const defaultNavigate = (url: string) => window.location.assign(url)

interface Props {
  /** Куда уходить при 401. Подменяется в тестах: jsdom не умеет переходов. */
  navigate?: (url: string) => void
}

export function ClinicSettingsScreen({ navigate = defaultNavigate }: Props) {
  const [load, setLoad] = useState<LoadState>({ status: 'loading' })
  const [form, setForm] = useState<ClinicForm>(EMPTY)
  const [saving, setSaving] = useState(false)
  const [invalid, setInvalid] = useState<string | undefined>(undefined)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const ctl = new AbortController()
    clinicSettings.load(ctl.signal).then(
      (r) => {
        setLoad({ status: 'ready', data: r.data })
        setForm(toForm(r.data))
      },
      (e: unknown) => {
        if (ctl.signal.aborted) return
        const err = asApiError(e)
        if (err.failure.kind === 'unauthenticated') {
          setLoad({ status: 'leaving' })
          navigate(loginUrl())
          return
        }
        setLoad({ status: 'failed', error: err })
      },
    )
    return () => ctl.abort()
  }, [attempt, navigate])

  const retry = () => {
    setLoad({ status: 'loading' })
    setAttempt((n) => n + 1)
  }

  const closeToast = useCallback(() => setToast(null), [])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setInvalid(undefined)
    try {
      const r = await clinicSettings.save(form)
      setLoad({ status: 'ready', data: r.data })
      setForm(toForm(r.data))
      setToast({ tone: r.tone, text: r.text })
    } catch (e) {
      const err = asApiError(e)
      if (err.failure.kind === 'unauthenticated') {
        setLoad({ status: 'leaving' })
        navigate(loginUrl())
        return
      }
      if (err.failure.kind === 'validation') setInvalid(err.field)
      setToast({ tone: 'err', text: err.text || T.offline })
    } finally {
      setSaving(false)
    }
  }

  if (load.status === 'leaving') return null

  if (load.status === 'failed') {
    const { error } = load
    return (
      <section className="dp-react-root">
        <h2><Icon name="clinic" /> {T.title}</h2>
        <div className="banner err" role="alert">{error.text || T.offline}</div>
        <p className="dp-actions">
          {error.failure.kind !== 'forbidden' && (
            <button type="button" className="savebtn" onClick={retry}>
              <Icon name="refresh" /> {T.retry}
            </button>
          )}
          <a href={legacyUrl()}>{T.legacy}</a>
        </p>
      </section>
    )
  }

  const data = load.status === 'ready' ? load.data : null
  const busy = data === null || saving
  const set = (patch: Partial<ClinicForm>) => setForm((f) => ({ ...f, ...patch }))

  return (
    <section className="dp-react-root" aria-busy={data === null}>
      <h2><Icon name="clinic" /> {T.title}</h2>
      {data?.template && <div className="banner warn">{data.hint}</div>}
      <form onSubmit={onSubmit}>
        <table className="set">
          <tbody>
            <Row id="dp-name" label={T.name} value={form.name} max={80} first
              invalid={invalid === 'name'} disabled={busy}
              onChange={(v) => set({ name: v })} />
            <Row id="dp-phone" label={T.phone} value={form.phone} max={30}
              invalid={invalid === 'phone'} disabled={busy}
              onChange={(v) => set({ phone: v })} />
            <Row id="dp-addr-ro" label={T.addrRo} value={form.address.ro} max={120}
              invalid={false} disabled={busy}
              onChange={(v) => set({ address: { ...form.address, ro: v } })} />
            <Row id="dp-addr-ru" label={T.addrRu} value={form.address.ru} max={120}
              invalid={false} disabled={busy}
              onChange={(v) => set({ address: { ...form.address, ru: v } })} />
          </tbody>
        </table>
        <p className="hint">{T.hintA}<Icon name="phone" /> {T.hintB}</p>
        <button className="savebtn" disabled={busy}>
          <Icon name="save" /> {T.save}
        </button>
      </form>
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}

interface RowProps {
  id: string
  label: string
  value: string
  /** Тот же потолок, что режет сервер (_val_clinic): ввод дальше не идёт. */
  max: number
  invalid: boolean
  disabled: boolean
  onChange: (value: string) => void
  /** Первый ряд задаёт ширину колонки подписей — как у старой таблицы. */
  first?: boolean
}

function Row({ id, label, value, max, invalid, disabled, onChange, first }: RowProps) {
  return (
    <tr>
      <th style={first ? { width: 180 } : undefined}>
        <label htmlFor={id}>{label}</label>
      </th>
      <td>
        <input
          id={id}
          type="text"
          value={value}
          maxLength={max}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      </td>
    </tr>
  )
}
