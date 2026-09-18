import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import type { DayForm, NewAppt, NewNote } from './day'

/* Диалог свободной ячейки «+» (C25.5b): записать пациента ИЛИ заблокировать
   часы заметкой стойки. Разметка — те же классы, что печатает `_slot_modal`.

   ⚠️ Новая ячейка — чистый диалог: экран пересоздаёт его по ключу «врач|час»,
   поэтому сброс полей не нужен ни одним эффектом. Расхождение со старой
   страницей записано осознанно: там диалог ОДИН на весь документ, и набранное
   имя переживало закрытие — на другой ячейке оно подставлялось снова.

   ⚠️ Получас меняет ТОЛЬКО время записи и заголовок. Заметка остаётся
   почасовой: блокировки живут часами, как и ячейки сетки.
   ⚠️ Конец блокировки — голый час из `note_ends`, и только больше начала.
   Обеденный час оттуда выпал, поэтому закончить в 14:00 при обеде 13–14
   нельзя — это правило сервера, а не недосмотр списка. */
const T = {
  appt: 'Programare',
  note: 'Notiță / blocare',
  service: 'Serviciu',
  name: 'Nume pacient',
  phone: 'Telefon',
  noPhone: 'fără telefon',
  birth: 'Data nașterii (opț.)',
  go: 'Adaugă programarea',
  text: 'ex.: pauză de masă, ședință, rezervat telefonic…',
  until: 'până la ora',
  goNote: 'Salvează notița (blochează orele)',
  close: 'Închide',
} as const

export interface Slot {
  dk: string
  /** Имя врача — оно стоит в заголовке диалога. */
  name: string
  /** Час ячейки, «HH:00». */
  hour: string
}

interface Props {
  open: boolean
  slot: Slot
  date: string
  form: DayForm
  noteEnds: number[]
  busy: boolean
  onClose: () => void
  onAdd: (body: NewAppt) => Promise<boolean>
  onNote: (body: NewNote) => Promise<boolean>
}

export function SlotDialog({ open, slot, date, form, noteEnds, busy,
  onClose, onAdd, onNote }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [tab, setTab] = useState<'a' | 'n'>('a')
  const [half, setHalf] = useState<0 | 30>(0)
  const [service, setService] = useState(form.services[0]?.id ?? '')
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [noPhone, setNoPhone] = useState(false)
  const [birth, setBirth] = useState('')
  const [text, setText] = useState('')
  const [until, setUntil] = useState(0)

  const startH = Number(slot.hour.split(':')[0])
  const ends = noteEnds.filter((e) => e > startH)

  useEffect(() => {
    if (open) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [open])

  const time = `${slot.hour.split(':')[0]}:${half ? '30' : '00'}`

  async function submitAppt(e: FormEvent) {
    e.preventDefault()
    const ok = await onAdd({ date, time, doctor: slot.dk, service, name,
      phone: noPhone ? '' : phone, nophone: noPhone, birth })
    if (ok) onClose()
  }

  async function submitNote(e: FormEvent) {
    e.preventDefault()
    const ok = await onNote({ date, time: slot.hour, doctor: slot.dk, text,
      until: until || ends[0] || startH + 1 })
    if (ok) onClose()
  }

  return (
    <dialog ref={ref} onClose={onClose}>
      <div className="dlg-head">
        <span>{slot.name} — {time}</span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <div className="dlg-tabs">
        <button type="button" className={`tabbtn${tab === 'a' ? ' on' : ''}`}
                onClick={() => setTab('a')}><Icon name="user" /> {T.appt}</button>
        <button type="button" className={`tabbtn${tab === 'n' ? ' on' : ''}`}
                onClick={() => setTab('n')}><Icon name="note" /> {T.note}</button>
      </div>
      {tab === 'a' ? (
        <form className="dlg-form" onSubmit={submitAppt}>
          <div className="halfpick" role="group" aria-label="Ora">
            <button type="button" className={`hp${half ? '' : ' on'}`}
                    onClick={() => setHalf(0)}>{slot.hour.split(':')[0]}:00</button>
            <button type="button" className={`hp${half ? ' on' : ''}`}
                    onClick={() => setHalf(30)}>{slot.hour.split(':')[0]}:30</button>
          </div>
          <select value={service} onChange={(e) => setService(e.target.value)}
                  aria-label={T.service}>
            {form.services.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
          </select>
          <input value={name} onChange={(e) => setName(e.target.value)}
                 placeholder={T.name} required />
          <input value={noPhone ? '' : phone} onChange={(e) => setPhone(e.target.value)}
                 placeholder={T.phone} required={!noPhone} disabled={noPhone} />
          <label className="nophone">
            <input type="checkbox" checked={noPhone}
                   onChange={(e) => setNoPhone(e.target.checked)} /> {T.noPhone}
          </label>
          <label className="dlab">{T.birth}
            <input type="date" value={birth} max={form.birth_max}
                   onChange={(e) => setBirth(e.target.value)} />
          </label>
          <button disabled={busy}>{T.go}</button>
        </form>
      ) : (
        <form className="dlg-form" onSubmit={submitNote}>
          <input value={text} onChange={(e) => setText(e.target.value)}
                 placeholder={T.text} maxLength={120} required />
          <label className="dlab">{T.until}
            <select value={until || ends[0] || ''}
                    onChange={(e) => setUntil(Number(e.target.value))}>
              {ends.map((e) => <option key={e} value={e}>{e}:00</option>)}
            </select>
          </label>
          <button disabled={busy || !ends.length}>{T.goNote}</button>
        </form>
      )}
    </dialog>
  )
}
