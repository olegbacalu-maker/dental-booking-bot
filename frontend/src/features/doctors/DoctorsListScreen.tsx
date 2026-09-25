import { useCallback, useState, type FormEvent } from 'react'
import { AppLink, useAppNavigate } from '../../components/AppLink'
import { Avatar } from '../../components/Avatar'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { asApiError } from '../../services/api'
import { doctors, type DoctorsList, type DoctorSummary } from './doctors'

/* Подписи экрана — те же слова, что на старой странице «Medici». Состояния
   врача, часы, цвета и цифры приходят с сервера. */
const T = {
  panel: 'Panou',
  settings: 'Setările clinicii',
  sameColor:
    'Toți medicii au aceeași culoare, deci cardurile lor din programul zilei nu se disting.',
  autoColors: 'Culori automate',
  newDoctor: 'Medic nou',
  phName: 'Dr. Nume Prenume',
  phSpec: 'Specializare (ex. Terapie)',
  add: '+ Adaugă medic',
  hint:
    'Medicul nu se șterge niciodată: programările lui păstrează legătura cu el. ' +
    '«În concediu» = pauză temporară, «Arhivat» = a plecat (posibil doar fără programări viitoare).',
  archive: 'Arhivă',
  archiveSub: '· medici care nu mai lucrează; istoricul rămâne',
  statN: 'programări · 30 zile',
  statPct: 'ocupare',
  statNoshow: 'neprezentări',
  empty: 'Niciun medic încă. Adăugați primul medic mai jos.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

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

  if (state.status === 'leaving') return null

  const nav = (
    <div className="nav">
      <AppLink href="/admin"><Icon name="home" /> {T.panel}</AppLink>
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

  return (
    <section className="dp-react-root" aria-busy={data === null}>
      {nav}
      {data?.same_color && (
        <div className="banner err">
          {T.sameColor}
          <button type="button" className="dp-inline-btn" onClick={onColors} disabled={busy}>
            <Icon name="palette" /> {T.autoColors}
          </button>
        </div>
      )}
      <div className="medgrid">
        {live.map((d) => <DoctorTile key={d.id} d={d} states={states} />)}
      </div>
      {data && data.doctors.length === 0 && <p className="hint">{T.empty}</p>}
      <h2><Icon name="plus" /> {T.newDoctor}</h2>
      <form className="add" onSubmit={onAdd}>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={T.phName}
          aria-label={T.phName}
          required
          maxLength={60}
          style={{ width: 260 }}
          disabled={busy || data === null}
        />
        <input
          type="text"
          value={spec}
          onChange={(e) => setSpec(e.target.value)}
          placeholder={T.phSpec}
          aria-label={T.phSpec}
          maxLength={60}
          style={{ width: 220 }}
          disabled={busy || data === null}
        />
        <button disabled={busy || data === null}>{T.add}</button>
      </form>
      <p className="hint">{T.hint}</p>
      {arch.length > 0 && (
        <>
          <h2>
            <Icon name="box" /> {T.archive}{' '}
            <small style={{ fontWeight: 400, color: 'var(--text3)' }}>{T.archiveSub}</small>
          </h2>
          <div className="medgrid">
            {arch.map((d) => <DoctorTile key={d.id} d={d} states={states} />)}
          </div>
        </>
      )}
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}

/** Карточка врача в сетке — та же разметка, что у серверной _med_card_html. */
function DoctorTile({ d, states }: { d: DoctorSummary; states: Record<string, string> }) {
  return (
    <AppLink
      className={d.status === 'activ' ? 'medcard' : 'medcard off'}
      href={`/admin/doctor-card/${encodeURIComponent(d.id)}`}
    >
      <div className="medhead">
        <Avatar color={d.color} initials={d.initials} photo={d.photo} />
        <div style={{ minWidth: 0 }}>
          <b>{d.name}</b>
          <small>{d.spec || '—'}</small>
        </div>
        <span className={`dbadge ${d.status}`} style={{ marginLeft: 'auto' }}>
          {states[d.status] ?? d.status}
        </span>
      </div>
      <div className="medmeta">
        {d.room && <span><Icon name="door" /> {d.room}</span>}
        {d.phone && <span><Icon name="phone" /> {d.phone}</span>}
        <span><Icon name="clock" /> {d.hours}</span>
      </div>
      <div className="medstats">
        <div><b>{d.stats.n}</b><span>{T.statN}</span></div>
        <div><b>{d.stats.pct}%</b><span>{T.statPct}</span></div>
        <div><b>{d.stats.noshow}</b><span>{T.statNoshow}</span></div>
      </div>
    </AppLink>
  )
}
