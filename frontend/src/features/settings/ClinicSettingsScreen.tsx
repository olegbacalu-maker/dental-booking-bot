import { useCallback, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { legacyUrl } from '../../utils/legacy'
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

const EMPTY: ClinicForm = { name: '', phone: '', address: { ro: '', ru: '' } }

function toForm(d: ClinicSettings): ClinicForm {
  return { name: d.name, phone: d.phone, address: { ro: d.address.ro, ru: d.address.ru } }
}

interface Props {
  /** Куда уходить при 401. Подменяется в тестах: jsdom не умеет переходов. */
  navigate?: (url: string) => void
}

/**
 * Данные грузит роутер (B2): был единственным экраном на своём `useEffect`
 * — со своим циклом загрузки, своим «уходим на вход» и своими копиями общих
 * `asApiError`/`legacyUrl`. Теперь цикл тот же, что у всех (`useRouteLoad`).
 */
export const loadClinicSettings: RouteLoad<ClinicSettings> = (signal) => clinicSettings.load(signal)

export function ClinicSettingsScreen({ navigate = defaultNavigate }: Props) {
  const { state: load, retry, replace, leaveIfSignedOut } = useRouteLoad<ClinicSettings>(navigate)
  /* Правка поверх данных загрузчика: `null` — полей не трогали, и форма
     показывает то, что пришло (или что вернуло сохранение). */
  const [draft, setDraft] = useState<ClinicForm | null>(null)
  const [saving, setSaving] = useState(false)
  const [invalid, setInvalid] = useState<string | undefined>(undefined)
  const [toast, setToast] = useState<ToastState | null>(null)

  const closeToast = useCallback(() => setToast(null), [])

  const data = load.status === 'ready' ? load.data : null
  const form = draft ?? (data ? toForm(data) : EMPTY)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setInvalid(undefined)
    try {
      const r = await clinicSettings.save(form)
      replace(r.data)
      setDraft(null)
      setToast({ tone: r.tone, text: r.text })
    } catch (e) {
      const err = asApiError(e)
      if (leaveIfSignedOut(err)) return
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

  const busy = data === null || saving
  const set = (patch: Partial<ClinicForm>) => setDraft({ ...form, ...patch })

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
