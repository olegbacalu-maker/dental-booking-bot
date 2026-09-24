import { useCallback, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError, type ApiResult } from '../../services/api'
import { settings, type SecurityData, type UserForm, type UserRow } from './settings'

const T = {
  pinTitle: 'Schimbă PIN',
  oldPin: 'PIN actual',
  newPin: 'PIN nou',
  repeat: 'repetați',
  change: 'Schimbă',
  usersTitle: 'Utilizatori',
  cols: { person: 'Persoana', access: 'Acces' },
  idLabel: 'id: ',
  lastLogin: 'ultima intrare: ',
  noDoctor: '— nu e medic —',
  pinOptional: 'PIN nou (opțional)',
  save: 'Salvează',
  remove: 'Șterge',
  confirm: 'Ștergeți contul {name}?',
  addName: 'Nume și prenume',
  addUid: 'id (ex. d2, ana)',
  addPin: 'PIN {min}–{max} cifre',
  add: '+ Adaugă utilizator',
  hint:
    'Intrarea se face cu PIN-ul personal, fără nume de utilizator — de aceea PIN-ul trebuie ' +
    'să fie unic în clinică. ',
  hintRoles: ' vede banii și setările, ',
  hintRest: ' — tot restul. Legătura cu un medic face ca jurnalul să scrie numele lui la ' +
    'fiecare deschidere de fișă. Pentru ',
  hintDirector: ' recomandăm un PIN de 6+ cifre — el vede banii și setările; intrările în ' +
    'program se văd în «Activitate recentă» (Statistici).',
  unavailable: 'Conturile există doar în ediția instalată pe calculatorul clinicii.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

const NEW_USER: UserForm = { uid: '', name: '', role: 'medic', doctor_id: '', pin: '' }

interface Props {
  navigate?: (url: string) => void
}

/** Данные экрана грузит роутер (B2.2), App.tsx › LOADS. */
export const loadSecuritySettings: RouteLoad<SecurityData> = (signal) => settings.security(signal)

/**
 * Смена своего PIN и учётки сотрудников. Правила (уникальность PIN, последний
 * директор, своя учётка) — на сервере, те же, что у форм; здесь только ввод.
 */
export function SecuritySettingsScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<SecurityData>(navigate)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [busy, setBusy] = useState(false)
  const [pins, setPins] = useState({ old_pin: '', new1: '', new2: '' })
  const [fresh, setFresh] = useState<UserForm>(NEW_USER)
  const closeToast = useCallback(() => setToast(null), [])

  function fail(e: unknown) {
    const err = asApiError(e)
    if (leaveIfSignedOut(err)) return
    setToast({ tone: 'err', text: err.text || T.offline })
  }
  const said = (r: ApiResult<unknown>) => setToast({ tone: r.tone, text: r.text })

  async function changePin(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const r = await settings.pinChange(pins.old_pin, pins.new1, pins.new2)
      setPins({ old_pin: '', new1: '', new2: '' })
      said(r)
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  async function saveUser(form: UserForm, after?: () => void) {
    setBusy(true)
    try {
      const r = await settings.userSave(form)
      replace(r.data)
      said(r)
      after?.()
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  async function removeUser(u: UserRow) {
    if (!window.confirm(T.confirm.replace('{name}', u.name))) return
    setBusy(true)
    try {
      const r = await settings.userDelete(u.id)
      replace(r.data)
      said(r)
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  if (state.status === 'leaving') return null
  if (state.status === 'failed') {
    const gone = state.error.failure.kind === 'server' && state.error.failure.status === 404
    return (
      <section className="dp-react-root">
        <h2><Icon name="key" /> {T.pinTitle}</h2>
        <LoadFailed error={state.error} onRetry={retry} {...(gone ? { text: T.unavailable } : {})} />
      </section>
    )
  }
  const data: SecurityData | null = state.status === 'ready' ? state.data : null
  const max = data?.pin.max ?? 8

  return (
    <section className="dp-react-root" aria-busy={data === null}>
      <h2><Icon name="key" /> {T.pinTitle}</h2>
      <form className="add" onSubmit={changePin}>
        <input type="password" value={pins.old_pin} placeholder={T.oldPin} aria-label={T.oldPin}
          inputMode="numeric" maxLength={max} required style={{ width: 140 }} disabled={busy || !data}
          onChange={(e) => setPins({ ...pins, old_pin: e.target.value })} />
        <input type="password" value={pins.new1} placeholder={T.newPin} aria-label={T.newPin}
          inputMode="numeric" maxLength={max} required style={{ width: 140 }} disabled={busy || !data}
          onChange={(e) => setPins({ ...pins, new1: e.target.value })} />
        <input type="password" value={pins.new2} placeholder={T.repeat} aria-label={T.repeat}
          inputMode="numeric" maxLength={max} required style={{ width: 140 }} disabled={busy || !data}
          onChange={(e) => setPins({ ...pins, new2: e.target.value })} />
        <button disabled={busy || !data}>{T.change}</button>
      </form>

      <h2><Icon name="users" /> {T.usersTitle}</h2>
      <table className="set">
        <thead><tr><th style={{ width: 220 }}>{T.cols.person}</th><th>{T.cols.access}</th><th /></tr></thead>
        <tbody>
          {data?.users.map((u) => (
            <UserRowForm key={u.id} user={u} data={data} busy={busy}
              onSave={(f) => saveUser(f)} onRemove={() => removeUser(u)} />
          ))}
        </tbody>
      </table>
      <form className="add" onSubmit={(e) => { e.preventDefault(); void saveUser(fresh, () => setFresh(NEW_USER)) }}>
        <input value={fresh.name} placeholder={T.addName} aria-label={T.addName} maxLength={60} required
          style={{ width: 200 }} disabled={busy || !data} onChange={(e) => setFresh({ ...fresh, name: e.target.value })} />
        <input value={fresh.uid} placeholder={T.addUid} aria-label={T.addUid} maxLength={20} required
          style={{ width: 130 }} disabled={busy || !data} onChange={(e) => setFresh({ ...fresh, uid: e.target.value })} />
        <select value={fresh.role} aria-label="rol" disabled={busy || !data}
          onChange={(e) => setFresh({ ...fresh, role: e.target.value })}>
          {Object.entries(data?.roles ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={fresh.doctor_id} aria-label="medic" disabled={busy || !data}
          onChange={(e) => setFresh({ ...fresh, doctor_id: e.target.value })}>
          <option value="">{T.noDoctor}</option>
          {data?.doctors.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <input type="password" value={fresh.pin} inputMode="numeric" maxLength={max} required
          placeholder={T.addPin.replace('{min}', String(data?.pin.min ?? '')).replace('{max}', String(max))}
          aria-label={T.addPin.replace('{min}', String(data?.pin.min ?? '')).replace('{max}', String(max))}
          style={{ width: 150 }} disabled={busy || !data} onChange={(e) => setFresh({ ...fresh, pin: e.target.value })} />
        <button disabled={busy || !data}>{T.add}</button>
      </form>
      <p className="hint">
        {T.hint}<b>Director</b>{T.hintRoles}<b>Recepție</b> și <b>Medic</b>{T.hintRest}<b>director</b>{T.hintDirector}
      </p>
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}

interface RowProps {
  user: UserRow
  data: SecurityData
  busy: boolean
  onSave: (form: UserForm) => void
  onRemove: () => void
}

/** Строка сотрудника: роль, врач, новый PIN (не обязателен) и сохранение. */
function UserRowForm({ user, data, busy, onSave, onRemove }: RowProps) {
  const [form, setForm] = useState<UserForm>({
    uid: user.id, name: user.name, role: user.role, doctor_id: user.doctor_id, pin: '',
  })
  return (
    <tr>
      <td>
        <b>{user.name}</b><br />
        <small className="dp-muted">{T.idLabel}{user.id}</small><br />
        <small className="dp-muted">{T.lastLogin}{user.last_login || '—'}</small>
      </td>
      <td>
        <form className="dp-user-row" onSubmit={(e) => { e.preventDefault(); onSave(form); setForm({ ...form, pin: '' }) }}>
          <select value={form.role} aria-label={`rol ${user.id}`} disabled={busy}
            onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {Object.entries(data.roles).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select value={form.doctor_id} aria-label={`medic ${user.id}`} disabled={busy}
            onChange={(e) => setForm({ ...form, doctor_id: e.target.value })}>
            <option value="">{T.noDoctor}</option>
            {data.doctors.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <input type="password" value={form.pin} placeholder={T.pinOptional} aria-label={`PIN ${user.id}`}
            inputMode="numeric" maxLength={data.pin.max} style={{ width: 150 }} disabled={busy}
            onChange={(e) => setForm({ ...form, pin: e.target.value })} />
          <button disabled={busy}>{T.save}</button>
        </form>
      </td>
      <td>
        <button type="button" className="rowdel" disabled={busy} onClick={onRemove}>{T.remove}</button>
      </td>
    </tr>
  )
}
