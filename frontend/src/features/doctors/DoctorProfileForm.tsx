import { useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { asApiError, type ApiResult } from '../../services/api'
import { DoctorRooms } from './DoctorRooms'
import { doctors, type DoctorCard, type DoctorProfile } from './doctors'

const T = {
  name: 'Nume',
  spec: 'Specializare',
  phone: 'Telefon intern',
  email: 'E-mail (opțional)',
  hours: 'Program personal (de la / până la)',
  from: 'de la',
  to: 'până la',
  color: 'Culoare în calendar',
  auto: 'automată',
  state: 'Starea medicului',
  save: 'Salvează',
} as const

function profileOf(c: DoctorCard): DoctorProfile {
  const rooms = c.rooms?.length ? c.rooms.map((r) => ({ name: r.name }))
    : c.room ? [{ name: c.room }] : []
  return {
    name: c.name, spec: c.spec, room: c.room, rooms, phone: c.phone, email: c.email,
    color: c.color, auto_color: c.auto_color,
    work_from: c.work_from, work_to: c.work_to, status: c.status,
  }
}

function range(from: number, to: number): number[] {
  const out: number[] = []
  for (let h = from; h <= to; h += 1) out.push(h)
  return out
}

interface Props {
  card: DoctorCard
  onSaved: (r: ApiResult<DoctorCard>) => void
  onFail: (e: unknown) => void
}

/** Данные и программа врача — те же поля и те же правила, что у старой формы
 *  (POST /api/doctors/{dk} зовёт ту же _save_doctor). */
export function DoctorProfileForm({ card, onSaved, onFail }: Props) {
  const [form, setForm] = useState<DoctorProfile>(() => profileOf(card))
  const [saving, setSaving] = useState(false)
  const [invalid, setInvalid] = useState<string | undefined>(undefined)
  const set = (patch: Partial<DoctorProfile>) => setForm((f) => ({ ...f, ...patch }))
  const hour = (v: string): number | null => (v === '' ? null : Number(v))

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setInvalid(undefined)
    try {
      /* пустые строки списка — не кабинеты; `room` едет именем первого, как
         его читает прежняя версия программы */
      const rooms = (form.rooms ?? []).map((r) => ({ name: r.name.trim() })).filter((r) => r.name)
      const r = await doctors.save(card.id, { ...form, rooms, room: rooms[0]?.name ?? '' })
      setForm(profileOf(r.data))
      onSaved(r)
    } catch (err) {
      const apiErr = asApiError(err)
      if (apiErr.field) setInvalid(apiErr.field)
      onFail(apiErr)
    } finally {
      setSaving(false)
    }
  }

  const hours = range(card.hours.min, card.hours.max)

  return (
    <form className="fform" onSubmit={onSubmit}>
      <input
        value={form.name}
        onChange={(e) => set({ name: e.target.value })}
        placeholder={T.name}
        aria-label={T.name}
        maxLength={60}
        required
        aria-invalid={invalid === 'name' || undefined}
        disabled={saving}
      />
      <input
        value={form.spec}
        onChange={(e) => set({ spec: e.target.value })}
        placeholder={T.spec}
        aria-label={T.spec}
        maxLength={60}
        disabled={saving}
      />
      <DoctorRooms
        value={(form.rooms ?? []).map((r) => r.name)}
        known={(card.rooms_all ?? []).map((r) => r.name)}
        max={card.rooms_max ?? 3}
        invalid={invalid === 'rooms'}
        disabled={saving}
        onChange={(names) => set({ rooms: names.map((name) => ({ name })) })}
      />
      <div className="r2">
        <input
          value={form.phone}
          onChange={(e) => set({ phone: e.target.value })}
          placeholder={T.phone}
          aria-label={T.phone}
          maxLength={30}
          disabled={saving}
        />
      </div>
      <input
        value={form.email}
        onChange={(e) => set({ email: e.target.value })}
        placeholder={T.email}
        aria-label={T.email}
        maxLength={80}
        disabled={saving}
      />
      <div className="dp-field-label">{T.hours}</div>
      <div className="r2">
        <select
          aria-label={T.from}
          value={form.work_from ?? ''}
          onChange={(e) => set({ work_from: hour(e.target.value) })}
          disabled={saving}
        >
          <option value="">—</option>
          {hours.map((h) => <option key={h} value={h}>{h}:00</option>)}
        </select>
        <select
          aria-label={T.to}
          value={form.work_to ?? ''}
          onChange={(e) => set({ work_to: hour(e.target.value) })}
          disabled={saving}
        >
          <option value="">—</option>
          {hours.slice(1).map((h) => <option key={h} value={h}>{h}:00</option>)}
        </select>
      </div>
      <div className="dp-field-label">{T.color}</div>
      <div className="r2" style={{ alignItems: 'center' }}>
        <input
          type="color"
          aria-label={T.color}
          value={form.color}
          onChange={(e) => set({ color: e.target.value, auto_color: false })}
          className="dp-color"
          disabled={saving}
        />
        <label className="dp-check">
          <input
            type="checkbox"
            checked={form.auto_color}
            onChange={(e) => set({ auto_color: e.target.checked })}
            disabled={saving}
          />{' '}
          {T.auto}
        </label>
      </div>
      <div className="dp-field-label">{T.state}</div>
      <select
        aria-label={T.state}
        value={form.status}
        onChange={(e) => set({ status: e.target.value })}
        disabled={saving}
      >
        {Object.entries(card.states).map(([k, v]) => (
          <option key={k} value={k}>{v.label} — {v.hint}</option>
        ))}
      </select>
      <button disabled={saving}><Icon name="save" /> {T.save}</button>
    </form>
  )
}
