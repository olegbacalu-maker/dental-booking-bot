import { useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import type { ApiResult } from '../../services/api'
import { doctors, type ServiceRow } from './doctors'

const T = { save: 'Salvează serviciile' } as const

interface Props {
  dk: string
  services: ServiceRow[]
  onSaved: (services: ServiceRow[], r: ApiResult<unknown>) => void
  onFail: (e: unknown) => void
}

/**
 * Галочки услуг врача. Правило «услуга не остаётся без активного врача» живёт
 * на сервере (_set_services) — здесь только выбор и отправка. Родитель
 * перемонтирует блок по key, когда сервер вернул новый список.
 */
export function DoctorServices({ dk, services, onSaved, onFail }: Props) {
  const [picked, setPicked] = useState<Set<string>>(
    () => new Set(services.filter((s) => s.checked).map((s) => s.id)),
  )
  const [saving, setSaving] = useState(false)

  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      const r = await doctors.setServices(dk, [...picked])
      onSaved(r.data.services, r)
    } catch (err) {
      onFail(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={onSubmit}>
      <div className="svcpick">
        {services.map((s) => (
          <label key={s.id}>
            <input
              type="checkbox"
              checked={picked.has(s.id)}
              onChange={() => toggle(s.id)}
              disabled={saving}
            />{' '}
            {s.name}<small>{s.note}</small>
          </label>
        ))}
      </div>
      <button className="savebtn" style={{ marginTop: 10 }} disabled={saving}>
        <Icon name="save" /> {T.save}
      </button>
    </form>
  )
}
