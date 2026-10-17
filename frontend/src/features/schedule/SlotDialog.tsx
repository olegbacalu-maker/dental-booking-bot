import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { hideDialog, showDialog } from '../patients/card/dialog'
import type { NewAppt, NewNote } from './day'
import { slotTimes, type FreeHalves, type Slot, type SlotFormView } from './slot'

/* Диалог свободной ячейки «+» (C25.5b): записать пациента ИЛИ заблокировать
   часы заметкой стойки. Разметка — те же классы, что печатает `_slot_modal`.

   ⚠️ Новая ячейка — чистый диалог: экран пересоздаёт его по ключу «врач|час»,
   поэтому сброс полей не нужен ни одним эффектом. Расхождение со старой
   страницей записано осознанно: там диалог ОДИН на весь документ, и набранное
   имя переживало закрытие — на другой ячейке оно подставлялось снова.
   ⭐ И это же держит набранное на ЖИВОМ экране (панель): состояние полей
   заводится при монтировании, а конверт приезжает каждые 12 секунд — пересевать
   их некому и незачем. Диалог визита добивается того же черновиком, потому что
   у него есть серверное значение, которое он показывает; здесь его нет.

   ⚠️ Оба времени считает `slotTimes`, а не два обработчика по месту: получас
   двигает время ЗАПИСИ и заголовок, начало заметки остаётся часовым, и теперь
   это правило с проверкой, а не намерение.
   ⚠️ Конец блокировки — голый час из `note_ends`, и только больше начала.
   Обеденный час оттуда выпал, поэтому закончить в 14:00 при обеде 13–14
   нельзя — это правило сервера, а не недосмотр списка.

   ⛔ Кнопка ЗАПЕРТА, пока команда в полёте (`busy`), и это не косметика:
   второй клик даёт честный отказ `dup`, но человек видел бы два ответа на одно
   действие. Ключа идемпотентности не нужно — нужна блокировка.
   ⛔ Диалог закрывается ТОЛЬКО на удаче. Отказ («интервал занят», «врач не
   работает в этот час») оставляет набранное на экране: закрыть форму, из
   которой ничего не записалось, значит потерять ввод и не сказать почему.
   ⛔ И отказ печатается ВНУТРИ окна (17.10): плашка экрана живёт на z-index
   80, а `<dialog>` — в top layer, и под открытым окном её не видно вовсе.
   Экран отдаёт слово отказа колбэком `fail`, а не плашкой.
   ⭐ Занятость стартов — подсказка по канве (`free`, как `busyAt` у переноса):
   занятый получас не нажать, оба заняты — кнопка выключена и сказано почему.
   Правду по-прежнему говорит сервер под своим замком: пока окно открыто, час
   мог занять второй администратор, и его отказ придёт тем же `fail`. */
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
  taken: 'ocupat',
  bothTaken: 'Medicul are deja programări la',
  and: 'și',
} as const

/** Слово отказа — колбэком в окно, не плашкой экрана. */
export type Fail = (text: string) => void

interface Props {
  open: boolean
  slot: Slot
  date: string
  form: SlotFormView
  noteEnds: number[]
  /** Какие старты часа свободны по канве — считает экран. */
  free: FreeHalves
  busy: boolean
  onClose: () => void
  onAdd: (body: NewAppt, fail: Fail) => Promise<boolean>
  onNote: (body: NewNote, fail: Fail) => Promise<boolean>
}

export function SlotDialog({ open, slot, date, form, noteEnds, free, busy,
  onClose, onAdd, onNote }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [tab, setTab] = useState<'a' | 'n'>('a')
  const [half, setHalf] = useState<0 | 30>(free.h0 ? 0 : 30)
  const [fail, setFail] = useState('')
  /* Канва приехала новой (после отказа экран перечитывает канал), и выбранный
     старт стал занят: переставить на свободный ещё при отрисовке — тот же
     приём, что у смены дня в DashScreen. Оба заняты — выбор не трогаем. */
  const none = !free.h0 && !free.h30
  if (!none && (half === 0 ? !free.h0 : !free.h30)) setHalf(free.h0 ? 0 : 30)
  const [service, setService] = useState(form.services[0]?.id ?? '')
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [noPhone, setNoPhone] = useState(false)
  const [birth, setBirth] = useState('')
  const [text, setText] = useState('')
  const [until, setUntil] = useState(0)

  const hh = slot.hour.split(':')[0] ?? ''
  const { atime, ntime, ends } = slotTimes(slot.hour, half, noteEnds)

  useEffect(() => {
    if (open) showDialog(ref.current)
    else hideDialog(ref.current)
  }, [open])

  async function submitAppt(e: FormEvent) {
    e.preventDefault()
    setFail('')
    const ok = await onAdd({ date, time: atime, doctor: slot.dk, service, name,
      phone: noPhone ? '' : phone, nophone: noPhone, birth }, setFail)
    if (ok) onClose()
  }

  async function submitNote(e: FormEvent) {
    e.preventDefault()
    setFail('')
    const ok = await onNote({ date, time: ntime, doctor: slot.dk, text,
      until: until || ends[0] || Number(hh) + 1 }, setFail)
    if (ok) onClose()
  }

  const pick = (h: 0 | 30) => { setHalf(h); setFail('') }
  const hp = (h: 0 | 30, ok: boolean) =>
    `hp${half === h ? ' on' : ''}${ok ? '' : ' taken'}`
  const warn = fail || (none ? `${T.bothTaken} ${hh}:00 ${T.and} ${hh}:30.` : '')
  const warnNode = warn ? <div className="banner err" role="alert">{warn}</div> : null

  return (
    <dialog ref={ref} onClose={onClose}>
      <div className="dlg-head">
        <span>{slot.name} — {atime}</span>
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
            <button type="button" className={hp(0, free.h0)} disabled={!free.h0}
                    onClick={() => pick(0)}>
              {hh}:00{!free.h0 && <small> · {T.taken}</small>}
            </button>
            <button type="button" className={hp(30, free.h30)} disabled={!free.h30}
                    onClick={() => pick(30)}>
              {hh}:30{!free.h30 && <small> · {T.taken}</small>}
            </button>
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
          {warnNode}
          <button disabled={busy || none}>{T.go}</button>
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
          {fail ? <div className="banner err" role="alert">{fail}</div> : null}
          <button disabled={busy || !ends.length}>{T.goNote}</button>
        </form>
      )}
    </dialog>
  )
}
