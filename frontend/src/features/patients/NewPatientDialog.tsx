import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Icon } from '../../components/Icon'
import { asApiError } from '../../services/api'
import type { ApiError } from '../../types/api'
import { patients } from './patients'

/* Диалог «Pacient nou» — те же поля и слова, что у старой страницы. Правило
   (без имени — отказ, тот же телефон — открывается существующая фиша) живёт
   на сервере; ответ несёт адрес фиши, куда и уходим — как редирект формы. */
const T = {
  title: '＋ Pacient nou',
  close: 'Închide',
  name: 'Nume și prenume',
  phone: 'Telefon',
  phPhone: 'ex. 069 123 456',
  noPhone: 'fără telefon',
  birth: 'Data nașterii',
  email: 'E-mail',
  doctor: 'Medic curant',
  hint:
    'Fișa se deschide imediat după salvare — acolo completați dinții, planul și ' +
    'documentele. Pacientul cu același telefon nu se dublează.',
  submit: 'Adaugă pacientul',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

interface Props {
  open: boolean
  doctors: string[]
  onClose: () => void
  /** Уход в фишу (новую или найденную по телефону) по адресу сервера. */
  navigate: (url: string) => void
  /** 401 — уходим на вход; true, если ушли. */
  leaveIfSignedOut: (err: ApiError) => boolean
}

/* jsdom не умеет showModal/close: тогда открываем атрибутом — форма та же. */
function show(d: HTMLDialogElement) {
  if (d.open) return
  if (typeof d.showModal === 'function') d.showModal()
  else d.setAttribute('open', '')
}

function hide(d: HTMLDialogElement) {
  if (!d.open) return
  if (typeof d.close === 'function') d.close()
  else d.removeAttribute('open')
}

export function NewPatientDialog({ open, doctors, onClose, navigate, leaveIfSignedOut }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [noPhone, setNoPhone] = useState(false)
  const [birth, setBirth] = useState('')
  const [email, setEmail] = useState('')
  const [doctor, setDoctor] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open) show(d)
    else hide(d)
  }, [open])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const r = await patients.create({
        name, phone: noPhone ? '' : phone, birth_date: birth, email, primary_doctor: doctor,
      })
      navigate(r.data.url)
    } catch (err) {
      const ae = asApiError(err)
      if (leaveIfSignedOut(ae)) return
      setError(ae.text || T.offline)
      setBusy(false)
    }
  }

  return (
    <dialog ref={ref} onClose={onClose}>
      <div className="dlg-head">
        <span>{T.title}</span>
        <button type="button" onClick={onClose} aria-label={T.close}><Icon name="close" /></button>
      </div>
      <form className="dlg-form" onSubmit={onSubmit}>
        {error && <div className="banner err" role="alert">{error}</div>}
        <label className="dlab">{T.name}
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={120}
            required
            aria-invalid={error ? true : undefined}
          />
        </label>
        <label className="dlab">{T.phone}
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            maxLength={40}
            placeholder={T.phPhone}
            disabled={noPhone}
          />
        </label>
        <label className="nophone">
          <input
            type="checkbox"
            checked={noPhone}
            onChange={(e) => {
              setNoPhone(e.target.checked)
              if (e.target.checked) setPhone('')
            }}
          />{' '}
          {T.noPhone}
        </label>
        <label className="dlab">{T.birth}
          <input type="date" value={birth} onChange={(e) => setBirth(e.target.value)} />
        </label>
        <label className="dlab">{T.email}
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            maxLength={120}
          />
        </label>
        <label className="dlab">{T.doctor}
          <select value={doctor} onChange={(e) => setDoctor(e.target.value)}>
            <option value="">—</option>
            {doctors.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <p className="hint" style={{ margin: 0 }}>{T.hint}</p>
        <button disabled={busy}>{T.submit}</button>
      </form>
    </dialog>
  )
}
