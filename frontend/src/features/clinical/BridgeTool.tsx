import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import { archIndex, type BridgeSave, type Odontogram } from './chart'

/* Мост (punte) — жест врача пилота (08-21): «selectezi 47-44 și meniu în
   care alegi punte». Пока режим включён, клик по зубу отмечает его, а не
   открывает инспектор; порядок и правила дуги проверяет сервер
   (bridge_norm) — здесь только удобство: крайние зубы — опоры по умолчанию,
   роль меняется кликом по фишке. Молочных мостов не бывает (> 50 — мимо). */
const T = {
  bar: 'Punte nouă:',
  barHint: 'click pe dinții punții (învecinați, aceeași arcadă)',
  cancel: 'Anulează',
  go: 'Continuă',
  title: 'Punte nouă',
  hint: 'Click pe un dinte pentru a schimba rolul: stâlp (Co) sau corp de punte (D).',
  doctorNone: 'Medic —',
  altPh: 'Materialul punții',
  save: 'Salvează puntea',
  close: 'Închide',
} as const

interface Props {
  model: Odontogram
  active: boolean
  picked: number[]
  busy: boolean
  onCancel: () => void
  onSave: (body: BridgeSave) => Promise<boolean>
}

export function BridgeBar({ model, active, picked, onCancel, onContinue }: {
  model: Odontogram; active: boolean; picked: number[]; onCancel: () => void; onContinue: () => void
}) {
  if (!active) return null
  const ord = [...picked].sort((a, b) => archIndex(model, a) - archIndex(model, b))
  return (
    <div className="br-bar">
      <b>{T.bar}</b> {T.barHint}{' '}
      <span>{ord.length ? ord.join(', ') : '—'}</span>
      <button type="button" className="pl-btn" onClick={onCancel}>{T.cancel}</button>
      <button type="button" className="pl-btn primary" disabled={ord.length < 2} onClick={onContinue}>{T.go}</button>
    </div>
  )
}

export function BridgeDialog({ model, open, picked, busy, onClose, onSave }: {
  model: Odontogram; open: boolean; picked: number[]; busy: boolean; onClose: () => void; onSave: Props['onSave']
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const ord = [...picked].sort((a, b) => archIndex(model, a) - archIndex(model, b))
  const [roles, setRoles] = useState<Record<number, string>>({})
  const [doctor, setDoctor] = useState('')
  const [material, setMaterial] = useState(model.materials[0]?.id ?? '')
  const [alt, setAlt] = useState('')
  const key = ord.join(',')
  const [seenKey, setSeenKey] = useState('')
  // крайние — опоры по умолчанию (пример врача: 47-45-43 опоры при теле 46/44);
  // выводится при открытии с новым набором, без эффекта
  if (open && key !== seenKey) {
    const next: Record<number, string> = {}
    ord.forEach((n, i) => { next[n] = i === 0 || i === ord.length - 1 ? 'stalp' : 'corp' })
    setRoles(next)
    setSeenKey(key)
  }

  useEffect(() => {
    if (open) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [open])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const ok = await onSave({
      teeth: ord.map((n) => [n, roles[n] ?? 'corp']), material, material_alt: alt, doctor,
    })
    if (ok) { setAlt(''); setSeenKey('') }
  }

  return (
    <dialog ref={ref} onClose={onClose}>
      <div className="dlg-head">
        <span>{T.title}</span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <form className="dlg-form" onSubmit={onSubmit}>
        <p className="hint dp-m0">{T.hint}</p>
        <div className="br-chips">
          {ord.map((n) => (
            <button
              key={n}
              type="button"
              className={`br-chip${roles[n] === 'stalp' ? ' stalp' : ''}`}
              onClick={() => setRoles((r) => ({ ...r, [n]: r[n] === 'stalp' ? 'corp' : 'stalp' }))}
            >
              {n} - {model.bridge_roles[roles[n] ?? 'corp'] ?? ''}
            </button>
          ))}
        </div>
        <select aria-label={T.doctorNone} value={doctor} onChange={(e) => setDoctor(e.target.value)}>
          <option value="">{T.doctorNone}</option>
          {model.doctors.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <select aria-label="Material" value={material} onChange={(e) => setMaterial(e.target.value)}>
          {model.materials.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select>
        {material === 'alt' && (
          <input value={alt} onChange={(e) => setAlt(e.target.value)} placeholder={T.altPh} aria-label={T.altPh} maxLength={40} />
        )}
        <button disabled={busy}><Icon name="save" /> {T.save}</button>
      </form>
    </dialog>
  )
}
