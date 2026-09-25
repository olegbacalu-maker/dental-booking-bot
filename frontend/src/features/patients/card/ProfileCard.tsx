import { useEffect, useRef, useState, type FormEvent } from 'react'
import { AppLink, useAppNavigate } from '../../../components/AppLink'
import { Icon } from '../../../components/Icon'
import type { IconName } from '../../../components/icons'
import type { CardActions } from './actions'
import { patientCard, type PatientCard, type ProfileForm } from './card'

/* «Date pacient»: те же строки, та же форма и те же слова, что у старой
   карточки; правила (имя обязательно, дата не в будущем, IDNP из 13 цифр,
   чужой номер называется вслух) живут на сервере. */
const T = {
  title: 'Date pacient',
  rows: {
    phone: 'Telefon', birth: 'Data nașterii', gender: 'Gen', idnp: 'IDNP', email: 'E-mail',
    address: 'Adresă', insurance: 'Asigurare', doctor: 'Medic curant', since: 'Pacient din',
  },
  noPhone: 'fără telefon',
  edit: 'Editează profilul',
  ph: {
    name: 'Nume', phone: 'Telefon', idnp: 'IDNP (opțional)', email: 'E-mail', address: 'Adresă',
    insurance: 'Asigurare (ex. CNAM activă)', file_no: 'Nr. dosar', notes: 'Notițe interne',
  },
  genderNone: 'Gen —', doctorNone: 'Medic curant —',
  langTitle: 'Limba documentelor tipărite',
  langRo: 'Documente în română', langRu: 'Документы по-русски',
  save: 'Salvează profilul',
  archive: 'Arhivează pacientul', unarchive: 'Scoate din arhivă',
  export: 'Descarcă datele pacientului',
  exportTitle: 'Copie completă a datelor — pentru cererea pacientului (Legea 195)',
  acord: 'Informare / acord — tipărire',
  acordTitle: 'Formular de informare cu datele pacientului, pentru semnare (Legea 195)',
  eraseTitle: 'Ștergerea datelor (Legea 195)',
  eraseDelete: 'Pacientul nu are înregistrări medicale — fișa va fi ',
  eraseDeleteB: 'ștearsă definitiv',
  eraseDeleteTail: ', împreună cu programările.',
  eraseAnon: 'Pacientul are înregistrări medicale, pe care clinica e obligată să le păstreze. Se șterg ',
  eraseAnonB: 'datele de identitate',
  eraseAnonTail: ' (nume, telefon, IDNP, adresă…); tratamentul rămâne sub numărul fișei.',
  irreversible: ' Acțiunea este ',
  irreversibleB: 'ireversibilă',
  eraseConfirm: 'Acțiunea este ireversibilă. Continuați?',
  erasePh: 'scrieți STERG',
  eraseBtnDelete: 'Șterge definitiv', eraseBtnAnon: 'Șterge datele personale',
} as const

function formOf(card: PatientCard): ProfileForm {
  const p = card.profile
  return {
    name: p.name, phone: p.phone, birth_date: p.birth_date, gender: p.gender, idnp: p.idnp,
    email: p.email, address: p.address, insurance: p.insurance, primary_doctor: p.primary_doctor,
    file_no: p.file_no, notes: p.notes, lang: p.lang,
  }
}

interface Props {
  card: PatientCard
  a: CardActions
  /** Форма раскрыта извне: отказ сервера с полем или «Notiță» из быстрых действий. */
  editOpen: boolean
  onEditOpen: (open: boolean) => void
  /** Ушли из фиши после полного удаления (адрес — от сервера). */
  navigate: (url: string) => void
  onFail: (e: unknown) => void
}

interface Draft {
  card: PatientCard
  form: ProfileForm
  noPhone: boolean
}

const fresh = (card: PatientCard): Draft => ({ card, form: formOf(card), noPhone: !card.profile.phone })

export function ProfileCard({ card, a, editOpen, onEditOpen, navigate, onFail }: Props) {
  const goTo = useAppNavigate(navigate)
  const p = card.profile
  /* Черновик формы привязан к ФИШЕ, с которой начат: свежая фиша после
     удачи даёт форме свои значения (сервер мог срезать длину и
     нормализовать дату), при отказе ввод человека не пропадает. Выводится
     при отрисовке, без эффекта — так велит правило хуков. */
  const [draft, setDraft] = useState<Draft>(() => fresh(card))
  const cur = draft.card === card ? draft : fresh(card)
  const { form, noPhone } = cur
  const [invalid, setInvalid] = useState('')
  const [confirm, setConfirm] = useState('')
  const [erasing, setErasing] = useState(false)
  const notesRef = useRef<HTMLTextAreaElement>(null)
  const set = (patch: Partial<ProfileForm>) =>
    setDraft((d) => { const b = d.card === card ? d : fresh(card); return { ...b, form: { ...b.form, ...patch } } })
  const setNoPhone = (on: boolean) =>
    setDraft((d) => { const b = d.card === card ? d : fresh(card); return { ...b, noPhone: on, form: on ? { ...b.form, phone: '' } : b.form } })

  useEffect(() => {
    if (editOpen) notesRef.current?.focus({ preventScroll: true })
  }, [editOpen])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setInvalid('')
    const err = await a.act(() => patientCard.saveProfile(a.pid, a.views, { ...form, phone: noPhone ? '' : form.phone }))
    if (err?.field) setInvalid(err.field)
    else if (!err) onEditOpen(false)
  }

  async function onErase(e: FormEvent) {
    e.preventDefault()
    if (!window.confirm(T.eraseConfirm)) return
    setErasing(true)
    try {
      const r = await patientCard.erase(a.pid, a.views, confirm)
      if ('url' in r.data) {
        goTo(r.data.url)          // фиши больше нет — в список, переходом (B4)
        return
      }
      /* обезличено: фиша осталась — показываем её через тот же путь, что и
         любое действие (свежая фиша + плашка) */
      await a.act(() => Promise.resolve({ ...r, data: r.data as PatientCard }))
    } catch (err) {
      onFail(err)
    } finally {
      setErasing(false)
    }
  }

  const row = (label: string, val: string, icon: IconName) => (
    <div className="frow">
      <span>{label}</span>
      <span className="v">{val || '—'}</span>
      <span className="ic"><Icon name={icon} /></span>
    </div>
  )

  return (
    <div className="fcard">
      <h3>{T.title}</h3>
      {p.phone ? row(T.rows.phone, p.phone, 'phone') : (
        <div className="frow">
          <span>{T.rows.phone}</span>
          <span className="v notel">{T.noPhone}</span>
          <span className="ic"><Icon name="phone-off" /></span>
        </div>
      )}
      {row(T.rows.birth, p.birth, 'cal')}
      {row(T.rows.gender, p.gender_label, 'pat')}
      {row(T.rows.idnp, p.idnp, 'id')}
      {row(T.rows.email, p.email, 'mail')}
      {row(T.rows.address, p.address, 'pin')}
      {row(T.rows.insurance, p.insurance, 'shield')}
      {row(T.rows.doctor, p.primary_doctor, 'med')}
      {row(T.rows.since, p.created, 'cal')}
      {p.notes && <div className="dp-notes"><Icon name="note" /> {p.notes}</div>}
      <button type="button" className="dp-pc-btn dp-pc-edit" onClick={() => onEditOpen(!editOpen)}>
        <Icon name="pen" /> {T.edit}
      </button>
      <form className="fform dp-pedit" onSubmit={onSubmit} style={{ display: editOpen ? 'flex' : 'none' }}>
        <input value={form.name} onChange={(e) => set({ name: e.target.value })} placeholder={T.ph.name}
               aria-label={T.ph.name} required aria-invalid={invalid === 'name' || undefined} />
        <input value={form.phone} onChange={(e) => set({ phone: e.target.value })} placeholder={T.ph.phone}
               aria-label={T.ph.phone} disabled={noPhone} />
        <label className="nophone">
          <input type="checkbox" checked={noPhone} onChange={(e) => setNoPhone(e.target.checked)} />
          {' '}{T.noPhone}
        </label>
        <div className="r2">
          <input type="date" value={form.birth_date} onChange={(e) => set({ birth_date: e.target.value })}
                 aria-label={T.rows.birth} aria-invalid={invalid === 'birth_date' || undefined} />
          <select value={form.gender} onChange={(e) => set({ gender: e.target.value })} aria-label={T.rows.gender}>
            <option value="">{T.genderNone}</option>
            <option value="m">M</option>
            <option value="f">F</option>
          </select>
        </div>
        <input value={form.idnp} onChange={(e) => set({ idnp: e.target.value })} placeholder={T.ph.idnp}
               aria-label={T.ph.idnp} maxLength={13} inputMode="numeric" aria-invalid={invalid === 'idnp' || undefined} />
        <input value={form.email} onChange={(e) => set({ email: e.target.value })} placeholder={T.ph.email} aria-label={T.ph.email} />
        <input value={form.address} onChange={(e) => set({ address: e.target.value })} placeholder={T.ph.address} aria-label={T.ph.address} />
        <input value={form.insurance} onChange={(e) => set({ insurance: e.target.value })} placeholder={T.ph.insurance} aria-label={T.ph.insurance} />
        <div className="r2">
          <select value={form.primary_doctor} onChange={(e) => set({ primary_doctor: e.target.value })} aria-label={T.rows.doctor}>
            <option value="">{T.doctorNone}</option>
            {card.options.doctors.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <input value={form.file_no} onChange={(e) => set({ file_no: e.target.value })} placeholder={T.ph.file_no} aria-label={T.ph.file_no} />
        </div>
        <select value={form.lang === 'ru' ? 'ru' : 'ro'} onChange={(e) => set({ lang: e.target.value })} title={T.langTitle} aria-label={T.langTitle}>
          <option value="ro">{T.langRo}</option>
          <option value="ru">{T.langRu}</option>
        </select>
        <textarea ref={notesRef} value={form.notes} onChange={(e) => set({ notes: e.target.value })} rows={2}
                  placeholder={T.ph.notes} aria-label={T.ph.notes} />
        <button disabled={a.busy}><Icon name="save" /> {T.save}</button>
      </form>
      <button type="button" className="dp-pc-btn dp-pc-sec" disabled={a.busy}
              onClick={() => { void a.act(() => patientCard.archive(a.pid, a.views, !card.archived)) }}>
        <Icon name={card.archived ? 'undo' : 'box'} /> {card.archived ? T.unarchive : T.archive}
      </button>
      <AppLink className="dp-pc-btn dp-pc-sec" href={`/admin/patient/${card.id}/export`} title={T.exportTitle}>
        <Icon name="download" /> {T.export}
      </AppLink>
      <AppLink className="dp-pc-btn dp-pc-sec" href={`/admin/patient/${card.id}/acord`} title={T.acordTitle}>
        <Icon name="clipboard" /> {T.acord}
      </AppLink>
      <details className="dp-erase">
        <summary>{T.eraseTitle}</summary>
        <div className="dp-erase-box">
          <p>
            {card.erasure === 'delete'
              ? <>{T.eraseDelete}<b>{T.eraseDeleteB}</b>{T.eraseDeleteTail}</>
              : <>{T.eraseAnon}<b>{T.eraseAnonB}</b>{T.eraseAnonTail}</>}
            {T.irreversible}<b>{T.irreversibleB}</b>.
          </p>
          <form onSubmit={onErase}>
            <input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder={T.erasePh}
                   aria-label={T.erasePh} required autoComplete="off" />
            <button disabled={erasing}>{card.erasure === 'delete' ? T.eraseBtnDelete : T.eraseBtnAnon}</button>
          </form>
        </div>
      </details>
    </div>
  )
}
