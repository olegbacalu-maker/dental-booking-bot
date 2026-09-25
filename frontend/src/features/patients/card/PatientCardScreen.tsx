import { startTransition, useCallback, useState } from 'react'
import { AppLink } from '../../../components/AppLink'
import { useLocation, useNavigate, useSearchParams } from 'react-router'
import { Icon } from '../../../components/Icon'
import { LoadFailed } from '../../../components/LoadFailed'
import { Toast, type ToastState } from '../../../components/Toast'
import { defaultNavigate } from '../../../hooks/useLoad'
import {
  queryParam, searchChangeKeepsData, useRouteLoad, type RouteLoad, type ScreenData,
} from '../../../hooks/useRouteLoad'
import { asApiError, type ApiResult } from '../../../services/api'
import type { ApiError } from '../../../types/api'
import { ActivityCard } from './ActivityCard'
import { AlertsCard } from './AlertsCard'
import { AnamnezaCard } from './AnamnezaCard'
import { AppointDialog } from './AppointDialog'
import { DocumentsCard } from './DocumentsCard'
import { FinanceCard } from './FinanceCard'
import { HeroKpi } from './HeroKpi'
import { OdontogramCard } from '../../clinical/OdontogramCard'
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
  navigate?: (url: string) => void
}

/**
 * Режим ленты — `?views=1` в АДРЕСЕ (лента с журналом доступа), и больше
 * ниоткуда (B2.3). ⚠️ Повтор ключа (`?views=1&views=0`) решает ПОСЛЕДНИЙ,
 * как у сервера (Starlette): `URLSearchParams.get` берёт первый, и на одном
 * и том же адресе клиент и сервер показали бы разное.
 */
const viewsOf = (q: URLSearchParams): boolean => queryParam(q, 'views') === '1'

const loadCard: RouteLoad<PatientCard> = (signal, params, q) =>
  patientCard.get(Number(params.pid), viewsOf(q), signal)

/* ⭐ Смена ОДНОГО query на том же пути — переключатель ленты: её экран уже
   принёс сам (`/activity`, без записи о просмотре). Полная загрузка —
   `GET /api/patients/{pid}` — это ОТКРЫТИЕ фиши, и каждый щелчок писал бы в
   журнал доступа лишнее «Fișa deschisă». Правило общее с поиском
   (`searchChangeKeepsData`): повтор и другой пациент перезапускают загрузчик. */
/** Данные фиши грузит роутер (B2.3): пациент — из пути, режим ленты — из query. */
export const loadPatientCard: ScreenData = { load: loadCard, shouldRevalidate: searchChangeKeepsData }

export function PatientCardScreen({ pid, navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<PatientCard>(navigate)
  /* Режим ленты читается из адреса, который ведёт РОУТЕР, — тот же, что у
     загрузчика; из него же `reload` и каждое действие (`a.views`). Своей
     копии нет: после перехода она разошлась бы с адресом, и запросы ушли бы
     в прежнем режиме. `navigate` в пропсах — уход на вход (документом),
     переходы роутером — `to`. */
  const [q] = useSearchParams()
  const views = viewsOf(q)
  const { pathname } = useLocation()
  const to = useNavigate()
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
     просмотре), адрес страницы повторяет режим — как ?views=1 старой.
     Сначала данные, потом адрес — через РОУТЕР (загрузчик на смену одного
     query не перезапускается, см. `searchChangeKeepsData`), и F5 на этом адресе
     откроет фишу в том же режиме. `replace`, как и было: щелчки не копят
     шаги «Назад»; query собирается заново (прежний ?msg= не тянется).
     ⚠️ Лента и режим адреса (из него `a.views`) обязаны смениться ОДНОЙ
     отрисовкой: переход роутера React рисует переходом (transition), а
     подмену ленты — обычным обновлением, и между ними был бы кадр, где лента
     уже с просмотрами, а действие ушло бы без ?views=1. */
  const onViews = useCallback(async (on: boolean) => {
    if (state.status !== 'ready') return
    const card = state.data
    try {
      const r = await patientCard.activity(pid, on)
      startTransition(() => {
        replace({ ...card, activity: r.data })
        void to(`${pathname}${on ? '?views=1' : ''}`, { replace: true })
      })
    } catch (e) {
      fail(e)
    }
  }, [state, pid, replace, fail, to, pathname])

  /* зуб из плана открывается в компактной одонтограмме (диалог зуба); запрос
     — объектом с меткой, чтобы повторный клик по тому же зубу тоже сработал */
  const [toothReq, setToothReq] = useState<{ n: number; k: number } | null>(null)
  const onTooth = useCallback((n: number) => setToothReq({ n, k: Date.now() }), [])

  const failCb = useCallback((e: unknown) => { fail(e) }, [fail])
  const say = useCallback((t: ToastState) => setToast(t), [])
  /* зуб записан — свежая фиша приезжает В ОТВЕТЕ записи (`?card=1`, режим
     ленты — из адреса): пилюли шапки и летопись зависят от зубов.
     ⛔ Не перечитывать `patientCard.get`: GET фиши — это ОТКРЫТИЕ, и каждое
     сохранение зуба писало бы в журнал доступа ложное «Fișa deschisă».
     Фиши нет только в ответе моста, а мосты правятся на детальной. */
  const onToothSaved = useCallback((fresh: unknown) => {
    if (fresh) replace(fresh as PatientCard)
  }, [replace])

  if (state.status === 'leaving') return null

  const nav = (
    <div className="nav">
      <AppLink href="/admin/search"><Icon name="chev-l" /> {T.patients}</AppLink>
      <AppLink href="/admin/all"><Icon name="clipboard" /> {T.schedule}</AppLink>
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
          <OdontogramCard pid={pid} views={views} say={say} onFail={failCb} onChanged={onToothSaved} open={toothReq} />
          <PlanCard card={card} a={a} onTooth={onTooth} />
          <FinanceCard card={card} a={a} />
          <DocumentsCard card={card} a={a} onFail={failCb} navigate={navigate} />
          <div className="fcard">
            <h3>{T.quick}</h3>
            <div className="qa">
              <button type="button" onClick={() => setBooking(true)}><Icon name="plus" /> {T.newVisit}</button>
              <AppLink href="#plan"><Icon name="tooth" /> {T.plan}</AppLink>
              <AppLink href="#docs"><Icon name="camera" /> {T.upload}</AppLink>
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
