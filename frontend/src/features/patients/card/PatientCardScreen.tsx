import { startTransition, useCallback, useState, type KeyboardEvent } from 'react'
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
import { chart, type Odontogram } from '../../clinical/chart'
import { OdontogramCard } from '../../clinical/OdontogramCard'
import { PlanCard } from './PlanCard'
import { ProfileCard } from './ProfileCard'
import { NextVisitCard, VisitsCard } from './VisitsCard'
import type { CardActions } from './actions'
import { patientCard, type PatientCard } from './card'

/* Фиша пациента (C18) — с 26.09 рабочее место с вкладками (B6, слово Олега:
   «не растянуто на весь экран, а по вкладкам»): шапка с пятью цифрами всегда
   сверху, ниже — одна вкладка за раз: Rezumat (ближайший визит, быстрые
   действия, летопись; справа предупреждения и история визитов), Odontogramă,
   Plan și plăți, Vizite, Documente, Date pacient (профиль и анамнез). Порядок
   карточек внутри — от старой страницы (решение Олега 08-09). Все расчёты и
   правила — на сервере; здесь состояния и формы. */
const T = {
  patients: 'Pacienți',
  schedule: 'Programări',
  quick: 'Acțiuni rapide',
  tabs: 'Secțiunile fișei',
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

/* ⭐ Вкладка — в АДРЕСЕ (`?tab=`), как режим ленты: F5 и «Назад» её помнят, а
   смена query на том же пути фишу не перечитывает (`searchChangeKeepsData`) —
   журнал доступа лишнего «Fișa deschisă» не получает. Умолчание в адрес не
   пишется. Неактивные вкладки НЕ смонтированы: после действия фиша приезжает
   без `odontogram`, и карточка одонтограммы при возврате грузит свежую модель
   сама (её запрос — не открытие фиши). */
const TABS = [
  ['rezumat', 'Rezumat'], ['odonto', 'Odontogramă'], ['plan', 'Plan și plăți'],
  ['vizite', 'Vizite'], ['docs', 'Documente'], ['date', 'Date pacient'],
] as const
type Tab = (typeof TABS)[number][0]
const tabOf = (q: URLSearchParams): Tab => {
  const t = queryParam(q, 'tab')
  return (TABS.some(([k]) => k === t) ? t : 'rezumat') as Tab
}
/** Query адреса из вкладки и режима ленты; умолчания не пишутся, прежний ?msg= не тянется. */
const qs = (tab: Tab, views: boolean): string => {
  const p = new URLSearchParams()
  if (tab !== 'rezumat') p.set('tab', tab)
  if (views) p.set('views', '1')
  const s = p.toString()
  return s ? `?${s}` : ''
}

/** Фиша плюс её одонтограмма — одним кадром. После ответа действия (`replace`)
 *  поля `odontogram` нет: карточка к тому моменту уже держит модель сама. */
type CardData = PatientCard & { odontogram?: Odontogram | null }

/* ⭐ Одонтограмма — ВМЕСТЕ с фишей, до первого кадра. Своим запросом после
   монтирования она приезжала на ~50 мс позже фиши и роняла всё, что под ней,
   на треть экрана (зонд CDP 25.09: layout-shift 0.046 при КАЖДОМ открытии
   фиши — Олег: «прыгание страницы» после «Vezi profilul complet»). Отказ
   карты фишу не валит: карточка тогда грузит её сама и покажет отказ. Журнал
   доступа этот GET не трогает — «Fișa deschisă» пишет только GET фиши. */
const loadCard: RouteLoad<CardData> = async (signal, params, q) => {
  const pid = Number(params.pid)
  const [r, odontogram] = await Promise.all([
    patientCard.get(pid, viewsOf(q), signal),
    Promise.resolve().then(() => chart.get(pid, signal)).then((x) => x.data, () => null),
  ])
  return { ...r, data: { ...r.data, odontogram } }
}

/* ⭐ Смена ОДНОГО query на том же пути — переключатель ленты: её экран уже
   принёс сам (`/activity`, без записи о просмотре). Полная загрузка —
   `GET /api/patients/{pid}` — это ОТКРЫТИЕ фиши, и каждый щелчок писал бы в
   журнал доступа лишнее «Fișa deschisă». Правило общее с поиском
   (`searchChangeKeepsData`): повтор и другой пациент перезапускают загрузчик. */
/** Данные фиши грузит роутер (B2.3): пациент — из пути, режим ленты — из query. */
export const loadPatientCard: ScreenData = { load: loadCard, shouldRevalidate: searchChangeKeepsData }

export function PatientCardScreen({ pid, navigate = defaultNavigate }: Props) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<CardData>(navigate)
  /* Режим ленты читается из адреса, который ведёт РОУТЕР, — тот же, что у
     загрузчика; из него же `reload` и каждое действие (`a.views`). Своей
     копии нет: после перехода она разошлась бы с адресом, и запросы ушли бы
     в прежнем режиме. `navigate` в пропсах — уход на вход (документом),
     переходы роутером — `to`. */
  const [q] = useSearchParams()
  const views = viewsOf(q)
  const tab = tabOf(q)
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
        void to(`${pathname}${qs(tab, on)}`, { replace: true })
      })
    } catch (e) {
      fail(e)
    }
  }, [state, pid, replace, fail, to, pathname, tab])

  /* зуб из плана открывается в компактной одонтограмме (диалог зуба); запрос
     — объектом с меткой, чтобы повторный клик по тому же зубу тоже сработал.
     План и одонтограмма — на разных вкладках: сперва вкладка, карточка
     монтируется и применяет просьбу, как только у неё есть модель. */
  const [toothReq, setToothReq] = useState<{ n: number; k: number } | null>(null)
  /* вкладка — адресом, `replace`: щелчки по вкладкам не копят шаги «Назад» */
  const goTab = useCallback((t: Tab) => {
    if (t !== tab) void to(`${pathname}${qs(t, views)}`, { replace: true })
  }, [to, pathname, views, tab])
  const onTooth = useCallback((n: number) => { setToothReq({ n, k: Date.now() }); goTab('odonto') }, [goTab])
  /* ←/→ (Home/End) ходят по вкладкам по кругу, фокус идёт следом: кнопки все в
     DOM, активной — tabIndex 0, остальным -1 (одна остановка Tab на полосу). */
  const onTabKey = useCallback((e: KeyboardEvent<HTMLDivElement>) => {
    const i = TABS.findIndex(([k]) => k === tab)
    const n = e.key === 'ArrowRight' ? (i + 1) % TABS.length
      : e.key === 'ArrowLeft' ? (i + TABS.length - 1) % TABS.length
        : e.key === 'Home' ? 0 : e.key === 'End' ? TABS.length - 1 : -1
    const next = n < 0 ? undefined : TABS[n]
    if (!next) return
    e.preventDefault()
    goTab(next[0])
    const btn = e.currentTarget.children[n]
    if (btn instanceof HTMLElement) btn.focus()
  }, [tab, goTab])

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
      <HeroKpi card={card} onBook={() => setBooking(true)} onPlan={() => goTab('plan')} />
      <div className="wtabs" role="tablist" aria-label={T.tabs} onKeyDown={onTabKey}>
        {TABS.map(([k, label]) => (
          <button key={k} id={`wtab-${k}`} type="button" role="tab" aria-selected={tab === k}
            aria-controls="wpanel" tabIndex={tab === k ? 0 : -1} className={tab === k ? 'on' : ''}
            onClick={() => goTab(k)}>{label}</button>
        ))}
      </div>
      <div id="wpanel" role="tabpanel" aria-labelledby={`wtab-${tab}`} className="wpanel">
        {tab === 'rezumat' && (
          <div className="pv2">
            <div className="pv2-main">
              <NextVisitCard card={card} />
              <div className="fcard">
                <h3>{T.quick}</h3>
                <div className="qa">
                  <button type="button" onClick={() => setBooking(true)}><Icon name="plus" /> {T.newVisit}</button>
                  <button type="button" onClick={() => goTab('plan')}><Icon name="tooth" /> {T.plan}</button>
                  <button type="button" onClick={() => goTab('docs')}><Icon name="camera" /> {T.upload}</button>
                  <button type="button" onClick={() => { setEditOpen(true); goTab('date') }}><Icon name="note" /> {T.note}</button>
                  <button type="button" onClick={() => window.print()}><Icon name="print" /> {T.print}</button>
                </div>
              </div>
              <ActivityCard activity={card.activity} onViews={(on) => { void onViews(on) }} />
            </div>
            <div className="pv2-side">
              <AlertsCard card={card} a={a} />
              <VisitsCard card={card} />
            </div>
          </div>
        )}
        {tab === 'odonto' && (
          <OdontogramCard pid={pid} views={views} say={say} onFail={failCb} onChanged={onToothSaved} open={toothReq}
            initial={card.odontogram ?? null} />
        )}
        {tab === 'plan' && (
          <>
            <PlanCard card={card} a={a} onTooth={onTooth} />
            <FinanceCard card={card} a={a} />
          </>
        )}
        {tab === 'vizite' && (
          <div className="pv2">
            <div className="pv2-main"><VisitsCard card={card} /></div>
            <div className="pv2-side"><NextVisitCard card={card} /></div>
          </div>
        )}
        {tab === 'docs' && <DocumentsCard card={card} a={a} onFail={failCb} navigate={navigate} />}
        {tab === 'date' && (
          <div className="pv2">
            <div className="pv2-main">
              <ProfileCard card={card} a={a} editOpen={editOpen} onEditOpen={setEditOpen} navigate={navigate} onFail={failCb} />
            </div>
            <div className="pv2-side"><AnamnezaCard card={card} a={a} /></div>
          </div>
        )}
      </div>
      <AppointDialog open={booking} name={card.name} appoint={card.appoint} a={a} onClose={() => setBooking(false)} />
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
