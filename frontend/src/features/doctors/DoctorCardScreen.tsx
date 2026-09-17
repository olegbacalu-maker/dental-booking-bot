import { useCallback, useState } from 'react'
import { Avatar } from '../../components/Avatar'
import { Icon } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { Toast, type ToastState } from '../../components/Toast'
import { defaultNavigate, useLoad } from '../../hooks/useLoad'
import { asApiError, type ApiResult } from '../../services/api'
import { DoctorPhoto } from './DoctorPhoto'
import { DoctorProfileForm } from './DoctorProfileForm'
import { DoctorServices } from './DoctorServices'
import { DoctorWeek } from './DoctorWeek'
import { doctors, type DoctorCard, type ServiceRow } from './doctors'

/* Подписи фиши — слова старой страницы; предупреждение об услугах, подписи
   состояний и все числа приходят с сервера. */
const T = {
  all: 'Toți medicii',
  day: 'Ziua medicului',
  panel: 'Panou',
  contact: 'Date de contact și program',
  hintA: 'Programul «—» = ca al clinicii. Culoarea se folosește în calendarul zilei. ',
  hintB: 'Arhivarea e posibilă doar fără programări viitoare (acum: ',
  services: 'Servicii pe care le face',
  servicesHint:
    'Serviciul fără bife explicite se oferă la toți medicii activi. Dacă scoateți bifa ' +
    'de la un astfel de serviciu, lista lui devine explicită — un medic nou va trebui bifat manual.',
  last30: 'Ultimele 30 de zile',
  rows: { n: 'Programări', pct: 'Ocupare', noshow: 'Neprezentări', future: 'Programări viitoare' },
  statsLink: 'Statistica întregii clinici',
  notFound: 'Medicul nu există sau a fost șters din profilul clinicii.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

interface Props {
  dk: string
  navigate?: (url: string) => void
}

export function DoctorCardScreen({ dk, navigate = defaultNavigate }: Props) {
  const load = useCallback((signal: AbortSignal) => doctors.card(dk, signal), [dk])
  const { state, retry, replace, leaveIfSignedOut } = useLoad(load, navigate)
  const [toast, setToast] = useState<ToastState | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

  const fail = useCallback(
    (e: unknown) => {
      const err = asApiError(e)
      if (leaveIfSignedOut(err)) return
      setToast({ tone: 'err', text: err.text || T.offline })
    },
    [leaveIfSignedOut],
  )
  const said = useCallback((r: ApiResult<unknown>) => setToast({ tone: r.tone, text: r.text }), [])

  if (state.status === 'leaving') return null

  const nav = (
    <div className="nav">
      <a href="/admin/medici"><Icon name="med" /> {T.all}</a>
      <a href={`/admin/doctor/${encodeURIComponent(dk)}`}><Icon name="cal" /> {T.day}</a>
      <a href="/admin"><Icon name="home" /> {T.panel}</a>
    </div>
  )

  if (state.status === 'failed') {
    const notFound = state.error.failure.kind === 'server' && state.error.failure.status === 404
    return (
      <section className="dp-react-root">
        {nav}
        <LoadFailed error={state.error} onRetry={retry} {...(notFound ? { text: T.notFound } : {})} />
      </section>
    )
  }

  if (state.status === 'loading') {
    return (
      <section className="dp-react-root" aria-busy="true">
        {nav}
        <div className="fisa med"><div className="fcol-l"><div className="fcard" /></div></div>
      </section>
    )
  }

  const card = state.data
  const onPhoto = (photo: string, r: ApiResult<unknown>) => {
    replace({ ...card, photo })
    said(r)
  }
  const onServices = (services: ServiceRow[], r: ApiResult<unknown>) => {
    replace({ ...card, services })
    said(r)
  }
  const onSaved = (r: ApiResult<DoctorCard>) => {
    replace(r.data)
    said(r)
  }

  return (
    <section className="dp-react-root">
      {nav}
      {card.warning && <div className="banner err">{card.warning}</div>}
      <div className="fisa med">
        <div className="fcol-l">
          <div className="fcard">
            <div className="fhead">
              <Avatar color={card.color} initials={card.initials} photo={card.photo} big />
              <div style={{ minWidth: 0 }}>
                <b>{card.name}</b>
                <small>{card.spec || '—'}</small>
                <span className={`dbadge ${card.status}`} style={{ display: 'inline-block', marginTop: 6 }}>
                  {card.states[card.status]?.label ?? card.status}
                </span>
              </div>
            </div>
            <DoctorPhoto dk={dk} photo={card.photo} maxMb={card.max_photo_mb} onDone={onPhoto} onFail={fail} />
          </div>
          <div className="fcard">
            <h3>{T.contact}</h3>
            <DoctorProfileForm card={card} onSaved={onSaved} onFail={fail} />
            <p className="hint" style={{ margin: '8px 0 0' }}>
              {T.hintA}{T.hintB}<b>{card.future}</b>).
            </p>
          </div>
        </div>
        <div className="fcol-c">
          <DoctorWeek dk={dk} week={card.week} today={card.today} />
        </div>
        <div className="fcol-r">
          <div className="fcard">
            <h3>{T.services}</h3>
            <DoctorServices
              key={card.services.map((s) => `${s.id}:${s.checked ? 1 : 0}`).join(',')}
              dk={dk}
              services={card.services}
              onSaved={onServices}
              onFail={fail}
            />
            <p className="hint" style={{ margin: '8px 0 0' }}>{T.servicesHint}</p>
          </div>
          <div className="fcard">
            <h3>{T.last30}</h3>
            <div className="frow"><span>{T.rows.n}</span><span className="v">{card.stats.n}</span></div>
            <div className="frow"><span>{T.rows.pct}</span><span className="v">{card.stats.pct}%</span></div>
            <div className="frow"><span>{T.rows.noshow}</span><span className="v">{card.stats.noshow}</span></div>
            <div className="frow"><span>{T.rows.future}</span><span className="v">{card.future}</span></div>
            <p className="hint" style={{ margin: '8px 0 0' }}>
              <a href="/admin/stats">{T.statsLink} <Icon name="out" /></a>
            </p>
          </div>
        </div>
      </div>
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
