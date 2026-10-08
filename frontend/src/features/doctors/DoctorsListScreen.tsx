import { useCallback, useState, type FormEvent } from 'react'
import { AppLink, useAppNavigate } from '../../components/AppLink'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { doctors, type DoctorsList, type DoctorSummary } from './doctors'

/* «Medici» по макету Олега (08.10, промпт 2): подзаголовок «N activi ·
   statistici pe ultimele 30 de zile», справа «Setările clinicii»; карточки
   врачей сеткой — аватар-кольцо цветом врача (тот же, что в календаре), имя,
   специализация, плашка состояния, кабинет и часы, три цифры между линиями,
   внизу выбор состояния и «Program ›» (день этого врача). «Arhivat» приглушает
   карточку, архивные стоят последними в той же сетке. Форма «Adaugă medic» с
   видимыми подписями; кнопка заперта, пока имя пустое.
   Состояния, часы, цвета и цифры приходят с сервера; смена состояния из
   карточки — тот же маршрут, что у фиши врача (`doctors.save`, полный профиль:
   частичной записи у сервера нет, поэтому профиль сначала читается). */
const T = {
  settings: 'Setările clinicii',
  subA: 'activi',
  subB: 'statistici pe ultimele 30 de zile',
  sameColor:
    'Toți medicii au aceeași culoare, deci cardurile lor din programul zilei nu se disting.',
  autoColors: 'Culori automate',
  newDoctor: 'Adaugă medic',
  lblName: 'Nume și prenume',
  lblSpec: 'Specializare',
  phName: 'Dr. Nume Prenume',
  phSpec: 'ex. Terapie',
  add: 'Adaugă medic',
  hintA: 'Medicul nu se șterge niciodată: programările lui păstrează legătura cu el. ',
  hintB: 'În concediu',
  hintC: ' = pauză temporară. ',
  hintD: 'Arhivat',
  hintE: ' = a plecat (posibil doar fără programări viitoare).',
  room: 'Cabinetul',
  clinicHours: 'Programul clinicii',
  statN: 'programări',
  statPct: 'ocupare',
  statNoshow: 'neprezentări',
  status: 'Status',
  schedule: 'Program ›',
  card: 'Fișa medicului',
  empty: 'Niciun medic încă. Adăugați primul medic mai jos.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

/** Класс плашки по состоянию — цвет смысла, не темы. */
const CHIP: Record<string, string> = { activ: 'ok', concediu: 'warn', arhivat: 'mute' }

interface Props {
  navigate?: (url: string) => void
}

/** Данные экрана грузит роутер (B2.2), App.tsx › LOADS. */
export const loadDoctorsList: RouteLoad<DoctorsList> = (signal) => doctors.list(signal)

export function DoctorsListScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<DoctorsList>(navigate)
  const goTo = useAppNavigate(navigate)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [name, setName] = useState('')
  const [spec, setSpec] = useState('')
  const [busy, setBusy] = useState(false)
  const closeToast = useCallback(() => setToast(null), [])

  function fail(e: unknown) {
    const err = asApiError(e)
    if (leaveIfSignedOut(err)) return
    setToast({ tone: 'err', text: err.text || T.offline })
  }

  async function onAdd(e: FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    try {
      const r = await doctors.add(name, spec)
      // как старая форма: в фишу нового врача, с плашкой сервера (?msg=new_med);
      // переходом (B4) — плашку несёт адрес, рисует оболочка
      goTo(`/admin/doctor-card/${encodeURIComponent(r.data.id)}?msg=${r.code}`)
    } catch (err) {
      fail(err)
      setBusy(false)
    }
  }

  async function onColors() {
    setBusy(true)
    try {
      const r = await doctors.resetColors()
      replace((await doctors.list()).data)
      setToast({ tone: r.tone, text: r.text })
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  /* Состояние из карточки: профиль читается и записывается целиком — у
     сервера нет частичной записи, а пустое поле стёрло бы телефон или часы.
     Отказ («Arhivat» при будущих записях) приходит словом сервера. */
  async function onStatus(dk: string, status: string) {
    setBusy(true)
    try {
      const c = (await doctors.card(dk)).data
      const r = await doctors.save(dk, {
        name: c.name, spec: c.spec, room: c.room, phone: c.phone, email: c.email,
        color: c.color, auto_color: c.auto_color, work_from: c.work_from, work_to: c.work_to, status,
      })
      replace((await doctors.list()).data)
      if (r.text) setToast({ tone: r.tone, text: r.text })
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  if (state.status === 'leaving') return null

  const nav = (
    <div className="nav">
      <AppLink href="/admin/settings"><Icon name="set" /> {T.settings}</AppLink>
    </div>
  )

  if (state.status === 'failed') {
    return (
      <section className="dp-react-root">
        {nav}
        <LoadFailed error={state.error} onRetry={retry} />
      </section>
    )
  }

  const data = state.status === 'ready' ? state.data : null
  const live = data?.doctors.filter((d) => !d.archived) ?? []
  const arch = data?.doctors.filter((d) => d.archived) ?? []
  const states = data?.states ?? {}
  const active = live.filter((d) => d.status === 'activ').length

  return (
    <section className="dp-react-root" aria-busy={data === null}>
      {nav}
      {data && <div className="sub"><b>{active}</b> {T.subA} · {T.subB}</div>}
      {data?.same_color && (
        <div className="banner err">
          {T.sameColor}
          <button type="button" className="dp-inline-btn" onClick={onColors} disabled={busy}>
            <Icon name="palette" /> {T.autoColors}
          </button>
        </div>
      )}
      <div className="dp-docs">
        {[...live, ...arch].map((d) => (
          <DoctorCardTile key={d.id} d={d} states={states} busy={busy} onStatus={onStatus} />
        ))}
      </div>
      {data && data.doctors.length === 0 && <p className="hint">{T.empty}</p>}
      <section className="dp-card dp-doc-add">
        <h2>{T.newDoctor}</h2>
        <form className="dp-doc-form" onSubmit={onAdd}>
          <label className="dp-doc-f">
            <span>{T.lblName}</span>
            <input
              type="text"
              className="dp-fld"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={T.phName}
              required
              maxLength={60}
              disabled={busy || data === null}
            />
          </label>
          <label className="dp-doc-f">
            <span>{T.lblSpec}</span>
            <input
              type="text"
              className="dp-fld"
              value={spec}
              onChange={(e) => setSpec(e.target.value)}
              placeholder={T.phSpec}
              maxLength={60}
              disabled={busy || data === null}
            />
          </label>
          <button className="dp-btn pri dp-doc-addbtn" disabled={busy || data === null || !name.trim()}>
            <Icon name="plus" /> {T.add}
          </button>
        </form>
        <p className="dp-doc-hint">{T.hintA}<b>{T.hintB}</b>{T.hintC}<b>{T.hintD}</b>{T.hintE}</p>
      </section>
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}

/** Карточка врача в сетке (макет 08.10). Имя ведёт в фишу врача; кабинет и
 *  часы — словами сервера («ca al clinicii» → «Programul clinicii»). */
function DoctorCardTile({ d, states, busy, onStatus }: {
  d: DoctorSummary; states: Record<string, string>; busy: boolean
  onStatus: (dk: string, status: string) => void
}) {
  /* слово сервера (layout.doctor_hours): «ca clinica» = часы клиники */
  const hours = d.hours === 'ca clinica' || d.hours === 'ca al clinicii' ? T.clinicHours : d.hours
  return (
    <article className={`dp-card dp-doc${d.archived ? ' off' : ''}`} data-dk={d.id}>
      <div className="dp-doc-head">
        <span className="dp-ring lg" style={{ borderColor: d.color }}>
          {d.photo ? <img src={d.photo} alt="" /> : d.initials}
        </span>
        <div className="dp-doc-who">
          <h2><AppLink href={`/admin/doctor-card/${encodeURIComponent(d.id)}`} title={T.card}>{d.name}</AppLink></h2>
          <small>{d.spec || '—'}</small>
        </div>
        <span className={`chip ${CHIP[d.status] ?? 'mute'} dbadge ${d.status}`}>{states[d.status] ?? d.status}</span>
      </div>
      <div className="dp-doc-meta">
        {d.room && <span><Icon name="door" /> {T.room} {d.room}</span>}
        <span><Icon name="clock" /> {hours}</span>
        {d.phone && <span><Icon name="phone" /> {d.phone}</span>}
      </div>
      <div className="dp-doc-stats">
        <div><b>{d.stats.n}</b><span>{T.statN}</span></div>
        <div><b>{d.stats.pct}%</b><span>{T.statPct}</span></div>
        <div><b>{d.stats.noshow}</b><span>{T.statNoshow}</span></div>
      </div>
      <div className="dp-doc-foot">
        <label className="dp-doc-status">
          <span>{T.status}</span>
          <select className="dp-sel" value={d.status} disabled={busy}
            aria-label={`${T.status}: ${d.name}`}
            onChange={(e) => onStatus(d.id, e.target.value)}>
            {Object.entries(states).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <AppLink className="dp-doc-lnk" href={`/admin/doctor/${encodeURIComponent(d.id)}`}>{T.schedule}</AppLink>
      </div>
    </article>
  )
}
