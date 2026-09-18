import { useCallback, useRef, useState } from 'react'
import { Icon } from '../../../components/Icon'
import { LoadFailed } from '../../../components/LoadFailed'
import { Toast, type ToastState } from '../../../components/Toast'
import { defaultNavigate, useLoad } from '../../../hooks/useLoad'
import { asApiError, type ApiResult } from '../../../services/api'
import type { ApiError } from '../../../types/api'
import { ActivityCard } from './ActivityCard'
import { AlertsCard } from './AlertsCard'
import { AnamnezaCard } from './AnamnezaCard'
import { AppointDialog } from './AppointDialog'
import { DocumentsCard } from './DocumentsCard'
import { FinanceCard } from './FinanceCard'
import { HeroKpi } from './HeroKpi'
import { OdontogramCard } from './OdontogramCard'
import { PlanCard } from './PlanCard'
import { ProfileCard } from './ProfileCard'
import { NextVisitCard, VisitsCard } from './VisitsCard'
import type { CardActions } from './actions'
import { patientCard, type PatientCard } from './card'

/* Фиша пациента (C18). Раскладка — та же, что у старой страницы: шапка,
   пять цифр, слева формула, план, платежи, документы, быстрые действия;
   справа ближайший визит, профиль, предупреждения, анамнез, летопись,
   история визитов (порядок правой колонки — решение Олега 08-09). Все
   расчёты и правила — на сервере; здесь состояния и формы. */
const T = {
  patients: 'Pacienți',
  schedule: 'Programări',
  quick: 'Acțiuni rapide',
  newVisit: 'Vizită nouă',
  plan: 'Plan de tratament',
  upload: 'Încarcă document',
  note: 'Notiță',
  print: 'Printează fișa',
  notFound: 'Fișa nu există sau a fost ștearsă.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
} as const

interface Props {
  pid: number
  /** ?views=1 в адресе: лента с журналом доступа. */
  views?: boolean
  navigate?: (url: string) => void
}

declare global {
  interface Window {
    /** Диалог зуба из куска одонтограммы (точка интеграции до C21). */
    openTooth?: (n: number) => void
  }
}

export function PatientCardScreen({ pid, views: viewsInit = false, navigate = defaultNavigate }: Props) {
  const [views, setViews] = useState(viewsInit)
  const viewsRef = useRef(viewsInit)
  const load = useCallback((signal: AbortSignal) => patientCard.get(pid, viewsRef.current, signal), [pid])
  const { state, retry, replace, leaveIfSignedOut } = useLoad(load, navigate)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [booking, setBooking] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const closeToast = useCallback(() => setToast(null), [])

  const fail = useCallback((e: unknown): ApiError => {
    const err = asApiError(e)
    if (!leaveIfSignedOut(err)) setToast({ tone: 'err', text: err.text || T.offline })
    return err
  }, [leaveIfSignedOut])

  /* Одно действие на все карточки: удача подменяет фишу и показывает плашку
     сервера, отказ — плашку и отдаёт ошибку форме (поле). */
  const act = useCallback(async (run: () => Promise<ApiResult<PatientCard>>): Promise<ApiError | null> => {
    setBusy(true)
    try {
      const r = await run()
      replace(r.data)
      if (r.text) setToast({ tone: r.tone, text: r.text })
      return null
    } catch (e) {
      return fail(e)
    } finally {
      setBusy(false)
    }
  }, [replace, fail])

  /* Переключение журнала доступа: лента отдельно (без новой записи о
     просмотре), адрес страницы повторяет режим — как ?views=1 старой. */
  const onViews = useCallback(async (on: boolean) => {
    if (state.status !== 'ready') return
    const card = state.data
    try {
      const r = await patientCard.activity(pid, on)
      viewsRef.current = on
      setViews(on)
      replace({ ...card, activity: r.data })
      window.history.replaceState(null, '', `${window.location.pathname}${on ? '?views=1' : ''}`)
    } catch (e) {
      fail(e)
    }
  }, [state, pid, replace, fail])

  const onTooth = useCallback((n: number) => {
    if (typeof window.openTooth === 'function') window.openTooth(n)
    else navigate(`/admin/patient/${pid}/odontograma?t=${n}`)
  }, [pid, navigate])

  const failCb = useCallback((e: unknown) => { fail(e) }, [fail])

  if (state.status === 'leaving') return null

  const nav = (
    <div className="nav">
      <a href="/admin/search"><Icon name="chev-l" /> {T.patients}</a>
      <a href="/admin/all"><Icon name="clipboard" /> {T.schedule}</a>
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
        <div className="hero dp-hero-wait" />
      </section>
    )
  }

  const card = state.data
  const a: CardActions = { pid, views, busy, act }

  return (
    <section className="dp-react-root" aria-busy={busy || undefined}>
      {nav}
      <HeroKpi card={card} onBook={() => setBooking(true)} />
      <div className="pv2">
        <div className="pv2-main">
          <OdontogramCard pid={pid} onFail={failCb} />
          <PlanCard card={card} a={a} onTooth={onTooth} />
          <FinanceCard card={card} a={a} />
          <DocumentsCard card={card} a={a} onFail={failCb} navigate={navigate} />
          <div className="fcard">
            <h3>{T.quick}</h3>
            <div className="qa">
              <button type="button" onClick={() => setBooking(true)}><Icon name="plus" /> {T.newVisit}</button>
              <a href="#plan"><Icon name="tooth" /> {T.plan}</a>
              <a href="#docs"><Icon name="camera" /> {T.upload}</a>
              <button type="button" onClick={() => setEditOpen(true)}><Icon name="note" /> {T.note}</button>
              <button type="button" onClick={() => window.print()}><Icon name="print" /> {T.print}</button>
            </div>
          </div>
        </div>
        <div className="pv2-side">
          <NextVisitCard card={card} />
          <ProfileCard card={card} a={a} editOpen={editOpen} onEditOpen={setEditOpen} navigate={navigate} onFail={failCb} />
          <AlertsCard card={card} a={a} />
          <AnamnezaCard card={card} a={a} />
          <ActivityCard activity={card.activity} onViews={(on) => { void onViews(on) }} />
          <VisitsCard card={card} />
        </div>
      </div>
      <AppointDialog open={booking} name={card.name} appoint={card.appoint} a={a} onClose={() => setBooking(false)} />
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
