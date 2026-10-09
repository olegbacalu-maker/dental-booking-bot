import { startTransition, useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type RefObject } from 'react'
import { AppLink } from '../../../components/AppLink'
import { useBlocker, useLocation, useNavigate, useSearchParams } from 'react-router'
import { ask } from '../../../components/confirm'
import { Icon } from '../../../components/Icon'
import { LoadFailed } from '../../../components/LoadFailed'
import { Toast, type ToastState } from '../../../components/Toast'
import { defaultNavigate } from '../../../hooks/useLoad'
import {
  intParam, queryParam, searchChangeKeepsData, useRouteLoad, type RouteLoad, type ScreenData,
} from '../../../hooks/useRouteLoad'
import { asApiError, type ApiResult } from '../../../services/api'
import type { ApiError } from '../../../types/api'
import { ActivityCard } from './ActivityCard'
import { AlertsCard } from './AlertsCard'
import { AnamnezaCard, anDirty, type AnDraft } from './AnamnezaCard'
import { AppointDialog } from './AppointDialog'
import { DocumentsCard, type DocsPick } from './DocumentsCard'
import { FinanceCard } from './FinanceCard'
import { HeroKpi } from './HeroKpi'
import { chart, type Odontogram } from '../../clinical/chart'
import { OdontogramTab } from '../../clinical/OdontogramTab'
import { PerioTab } from '../../clinical/PerioTab'
import { VisitTab } from '../../visits/VisitTab'
import { examOf, perio, type PerioModel } from '../../clinical/perio'
import { useCoarse } from '../../clinical/touch'
import { PlanCard } from './PlanCard'
import { ProfileCard } from './ProfileCard'
import { NextVisitCard, VisitsCard } from './VisitsCard'
import type { CardActions } from './actions'
import { patientCard, type PatientCard, type Visit } from './card'

/* Фиша пациента (C18) — с 26.09 рабочее место с вкладками (B6, слово Олега:
   «не растянуто на весь экран, а по вкладкам»): шапка с пятью цифрами всегда
   сверху, ниже — одна вкладка за раз: Rezumat (ближайший визит, быстрые
   действия, летопись; справа предупреждения и история визитов), Odontogramă,
   Parodontogramă, Plan și plăți, Vizite, Documente, Date pacient (профиль и
   анамнез). Порядок
   карточек внутри — от старой страницы (решение Олега 08-09). Все расчёты и
   правила — на сервере; здесь состояния и формы. */
const T = {
  patients: 'Pacienți',
  path: 'Cale',
  quick: 'Acțiuni rapide',
  tabs: 'Secțiunile fișei',
  newVisit: 'Vizită nouă',
  plan: 'Plan de tratament',
  upload: 'Încarcă document',
  note: 'Notiță',
  print: 'Printează fișa',
  notFound: 'Fișa nu există sau a fost ștearsă.',
  offline: 'Programul nu răspunde. Reîncercați sau deschideți varianta clasică.',
  unsaved: 'Anamneză nesalvată',
  leaveUnsaved: 'Anamneza are modificări nesalvate. Părăsiți fișa fără să le salvați?',
  leave: 'Părăsește',
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
  ['rezumat', 'Rezumat'], ['odonto', 'Odontogramă'], ['perio', 'Parodontogramă'],
  ['plan', 'Plan și plăți'], ['vizite', 'Vizite'], ['docs', 'Documente'], ['date', 'Date pacient'],
] as const
type Tab = (typeof TABS)[number][0]
const tabOf = (q: URLSearchParams): Tab => {
  const t = queryParam(q, 'tab')
  return (TABS.some(([k]) => k === t) ? t : 'rezumat') as Tab
}
/** Параметр, которым владеет САМА вкладка: осмотр у пародонтограммы, визит у
 *  истории; у остальных его нет, и смена вкладки его не тянет. */
const SUB: Partial<Record<Tab, string>> = { perio: 'exam', vizite: 'visit' }
/** Query адреса из вкладки, её параметра и режима ленты; умолчания не пишутся,
 *  прежний ?msg= не тянется. */
const qs = (tab: Tab, views: boolean, sub: number | null = null): string => {
  const p = new URLSearchParams()
  if (tab !== 'rezumat') p.set('tab', tab)
  const key = SUB[tab]
  if (key && sub !== null) p.set(key, String(sub))
  if (views) p.set('views', '1')
  const s = p.toString()
  return s ? `?${s}` : ''
}

/** Фиша плюс её одонтограмма и лист пародонтограммы — одним кадром. После ответа
 *  действия (`replace`) этих полей нет: вкладки к тому моменту держат модели сами. */
type CardData = PatientCard & { odontogram?: Odontogram | null; perioSheet?: PerioModel | null }

/* ⭐ Одонтограмма — ВМЕСТЕ с фишей, до первого кадра. Своим запросом после
   монтирования она приезжала на ~50 мс позже фиши и роняла всё, что под ней,
   на треть экрана (зонд CDP 25.09: layout-shift 0.046 при КАЖДОМ открытии
   фиши — Олег: «прыгание страницы» после «Vezi profilul complet»). Отказ
   карты фишу не валит: карточка тогда грузит её сама и покажет отказ. Журнал
   доступа этот GET не трогает — «Fișa deschisă» пишет только GET фиши.
   Лист пародонтограммы — тем же путём (07.10): своим запросом вкладка первым
   кадром рисовала «Se încarcă…», страница укорачивалась, и прокрутка прыгала
   наверх (Олег: «прыжок страницы»). Осмотр — из адреса, если фиша открыта на
   этой вкладке, иначе свежий; не тот осмотр вкладка не возьмёт (`PerioTab`). */
const loadCard: RouteLoad<CardData> = async (signal, params, q) => {
  const pid = Number(params.pid)
  const exam = tabOf(q) === 'perio' ? examOf(q) : null
  const [r, odontogram, perioSheet] = await Promise.all([
    patientCard.get(pid, viewsOf(q), signal),
    Promise.resolve().then(() => chart.get(pid, signal)).then((x) => x.data, () => null),
    Promise.resolve().then(() => perio.get(pid, exam, signal)).then((x) => x.data, () => null),
  ])
  return { ...r, data: { ...r.data, odontogram, perioSheet } }
}

/**
 * Панель вкладок держит прежнюю высоту, пока новая вкладка грузит своё.
 *
 * ⭐ Вкладка без данных (лист после записи осмотра, одонтограмма без засева,
 * другой осмотр, дневник визита) первым кадром рисует ожидание: панель
 * схлопывалась, страница укорачивалась, браузер поджимал прокрутку к началу — и
 * содержимое приезжало уже там (Олег 07.10: «прыжок страницы»). Высота — от
 * ResizeObserver, то есть ДО смены; держится, пока у панели есть ожидающий
 * ребёнок (`aria-busy`), и не дольше 4 с. Вкладка, нарисованная сразу, не
 * держится вовсе. Ожидание сцены 3D (внутри, своего размера) не считается.
 */
function useHoldPanel(key: string, ready: boolean): RefObject<HTMLDivElement | null> {
  const panel = useRef<HTMLDivElement>(null)
  const lastH = useRef(0)
  const prev = useRef(key)
  const off = useRef<(() => void) | null>(null)
  useEffect(() => {
    const el = panel.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => { if (!el.style.minHeight) lastH.current = el.offsetHeight })
    ro.observe(el)
    return () => ro.disconnect()
  }, [ready])
  useEffect(() => () => off.current?.(), [])
  useLayoutEffect(() => {
    if (prev.current === key) return
    prev.current = key
    const el = panel.current
    if (!el || typeof MutationObserver === 'undefined' || !lastH.current) return
    off.current?.()
    const busy = (): boolean => [...el.children].some((c) => c.getAttribute('aria-busy') === 'true')
    if (!busy()) return
    el.style.minHeight = `${lastH.current}px`
    let timer = 0
    let mo: MutationObserver | null = null
    const release = (): void => {
      mo?.disconnect()
      window.clearTimeout(timer)
      el.style.minHeight = ''
      off.current = null
    }
    mo = new MutationObserver(() => { if (!busy()) release() })
    mo.observe(el, { childList: true, subtree: true, attributes: true, attributeFilter: ['aria-busy'] })
    timer = window.setTimeout(release, 4000)
    off.current = release
  }, [key])
  return panel
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
  /* параметр вкладки — тоже адресом: осмотр (как `?exam=` страницы
     пародонтограммы) или визит, чей дневник открыт в истории */
  const sub = tab === 'perio' ? examOf(q) : tab === 'vizite' ? intParam(q, 'visit') : null
  const { pathname } = useLocation()
  const to = useNavigate()
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [booking, setBooking] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const closeToast = useCallback(() => setToast(null), [])
  /* ⭐ Черновик анамнеза — у экрана (01.10): вкладка «Date pacient»
     размонтируется при переходе, и набранное пропадало молча. Здесь он
     переживает вкладки; уход с ФИШИ с несохранённым — через вопрос. */
  const [anDraft, setAnDraft] = useState<AnDraft | null>(null)
  /* `?anamneza=1` (кнопка «Anamneză» в повестке панели, 09.10): фиша
     открывается сразу с раскрытым опросником — та же просьба, что из шапки */
  const [anTick, setAnTick] = useState(q.get('anamneza') ? 1 : 0)
  /* «Încarcă exemplarul semnat» из плана: вкладка Documente с нужной категорией */
  const [docsPick, setDocsPick] = useState<DocsPick | null>(null)
  const dirty = state.status === 'ready' && anDirty(anDraft, state.data.anamneza)
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    dirty && currentLocation.pathname !== nextLocation.pathname)
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    void ask({ text: T.leaveUnsaved, ok: T.leave, danger: true }).then((yes) => {
      if (yes) blocker.proceed()
      else blocker.reset()
    })
  }, [blocker])

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
        void to(`${pathname}${qs(tab, on, sub)}`, { replace: true })
      })
    } catch (e) {
      fail(e)
    }
  }, [state, pid, replace, fail, to, pathname, tab, sub])

  /* зуб из плана выбирается в рабочем столе одонтограммы (инспектор); запрос
     — объектом с меткой, чтобы повторный клик по тому же зубу тоже сработал.
     План и одонтограмма — на разных вкладках: сперва вкладка, карточка
     монтируется и применяет просьбу, как только у неё есть модель. */
  const [toothReq, setToothReq] = useState<{ n: number; k: number } | null>(null)
  /* вкладка — адресом, `replace`: щелчки по вкладкам не копят шаги «Назад» */
  const goTab = useCallback((t: Tab) => {
    if (t !== tab) void to(`${pathname}${qs(t, views)}`, { replace: true })
  }, [to, pathname, views, tab])
  const onTooth = useCallback((n: number) => { setToothReq({ n, k: Date.now() }); goTab('odonto') }, [goTab])
  /* смена осмотра во вкладке пародонтограммы — тем же адресом, replace */
  const goExam = useCallback((id: number | null) => {
    void to(`${pathname}${qs('perio', views, id)}`, { replace: true })
  }, [to, pathname, views])
  /* дневник визита — во вкладке Vizite, визит адресом (`?visit=`): ссылки
     истории ведут туда переходом, закрытие — та же вкладка без визита */
  const visitHref = useCallback((v: Visit) => `${pathname}${qs('vizite', views, v.id)}`, [pathname, views])
  const closeVisit = useCallback(() => { void to(`${pathname}${qs('vizite', views)}`, { replace: true }) }, [to, pathname, views])
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
  /* ⭐ Осмотр пародонта записан во вкладке Parodontogramă — одонтограмма,
     приехавшая С ФИШЕЙ, его уже не знает: слой «Parodont» в 3D и таблица точек
     в инспекторе показали бы прежний осмотр, а у пациента без осмотров кнопка
     «Parodont» осталась бы выключенной (Олег 07.10: «кнопка Parodont не
     работает»). Засев ЭТИХ данных фиши снимается, и вкладка одонтограммы при
     возврате грузит модель сама; новая загрузка фиши засевает снова. */
  const [perioStale, setPerioStale] = useState<CardData | null>(null)
  const onPerioChanged = useCallback(() => {
    if (state.status === 'ready') setPerioStale(state.data)
  }, [state])

  /* B7 · планшет: у кресла шапка пациента и пять плиток занимают весь первый
     экран альбомного iPad (замер 26.09: зуб 16 ниже края, касание в него не
     попадало). Пальцем при открытии клинической вкладки полоса вкладок встаёт
     под верхнюю панель — зубы сразу на экране. Мгновенно, без плавности: это
     переход, а не анимация. Мышью ничего не меняется. */
  const coarse = useCoarse()
  const strip = useRef<HTMLDivElement>(null)
  const ready = state.status === 'ready'
  useEffect(() => {
    if (!coarse || !ready || (tab !== 'odonto' && tab !== 'perio')) return
    const el = strip.current
    if (!el) return
    const bar = document.querySelector('.main .top')?.getBoundingClientRect().bottom ?? 0
    const dy = el.getBoundingClientRect().top - bar - 8
    if (dy > 8) window.scrollBy({ top: dy, behavior: 'auto' })
  }, [coarse, ready, tab])

  /* панель вкладок: прежняя высота, пока новая вкладка (или осмотр, визит) грузит своё */
  const panel = useHoldPanel(`${tab}:${sub ?? ''}`, ready)

  if (state.status === 'leaving') return null

  /* Хлебные крошки «Pacienți › Nume» (макет 08.10) — подпись раздела (`.sub`
     под заголовком оболочки); сервер отдаёт ему пустую. Имя — когда фиша
     приехала, до того — номер. */
  const nav = (
    <nav className="sub dp-crumbs" aria-label={T.path}>
      <AppLink href="/admin/search">{T.patients}</AppLink>
      <span className="dp-crumb-sep" aria-hidden="true">›</span>
      <b>{state.status === 'ready' ? state.data.name || `#${pid}` : `#${pid}`}</b>
    </nav>
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
  /* адрес фиши с текущей вкладкой — куда вернёт «назад» с печатного листа */
  const here = `${pathname}${qs(tab, views, sub)}`
  const a: CardActions = { pid, views, busy, act, back: here }

  return (
    <section className="dp-react-root" aria-busy={busy || undefined}>
      {nav}
      <HeroKpi card={card} back={here} onBook={() => setBooking(true)} onPlan={() => goTab('plan')}
        onAnamneza={() => { setAnTick((t) => t + 1); goTab('date') }}
        onDoctor={() => { setEditOpen(true); goTab('date') }} />
      <div ref={strip} className="wtabs" role="tablist" aria-label={T.tabs} onKeyDown={onTabKey}>
        {TABS.map(([k, label]) => (
          <button key={k} id={`wtab-${k}`} type="button" role="tab" aria-selected={tab === k}
            aria-controls="wpanel" tabIndex={tab === k ? 0 : -1} className={tab === k ? 'on' : ''}
            title={k === 'date' && dirty ? T.unsaved : undefined}
            onClick={() => goTab(k)}>
            {label}
            {/* точка — только глазу: имя вкладки для читалки и проверок остаётся прежним */}
            {k === 'date' && dirty && <i className="wtab-dot" aria-hidden="true" />}
          </button>
        ))}
      </div>
      <div ref={panel} id="wpanel" role="tabpanel" aria-labelledby={`wtab-${tab}`} className="wpanel">
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
              <AlertsCard card={card} a={a} onAnamneza={() => { setAnTick((t) => t + 1); goTab('date') }} />
              <VisitsCard card={card} hrefOf={visitHref} />
            </div>
          </div>
        )}
        {tab === 'odonto' && (
          <OdontogramTab pid={pid} views={views} say={say} onFail={failCb} onChanged={onToothSaved} open={toothReq}
            initial={perioStale === card ? null : card.odontogram ?? null} />
        )}
        {tab === 'perio' && (
          <PerioTab pid={pid} exam={sub} onExam={goExam} say={say} onFail={failCb} onChanged={onPerioChanged}
            initial={perioStale === card ? null : card.perioSheet ?? null} />
        )}
        {tab === 'plan' && (
          <>
            <PlanCard card={card} a={a} onTooth={onTooth}
              onUploadSigned={(category) => { setDocsPick({ category, k: Date.now() }); goTab('docs') }} />
            <FinanceCard card={card} a={a} />
          </>
        )}
        {tab === 'vizite' && sub !== null && (
          <VisitTab pid={pid} aid={sub} onClose={closeVisit} say={say} onFail={failCb} />
        )}
        {tab === 'vizite' && sub === null && (
          <div className="pv2">
            <div className="pv2-main"><VisitsCard card={card} hrefOf={visitHref} /></div>
            <div className="pv2-side"><NextVisitCard card={card} /></div>
          </div>
        )}
        {tab === 'docs' && <DocumentsCard card={card} a={a} onFail={failCb} navigate={navigate} pick={docsPick} />}
        {tab === 'date' && (
          <div className="pv2">
            <div className="pv2-main">
              <ProfileCard card={card} a={a} editOpen={editOpen} onEditOpen={setEditOpen} navigate={navigate} onFail={failCb} />
            </div>
            <div className="pv2-side">
              <AnamnezaCard card={card} a={a} draft={anDraft} onDraft={setAnDraft} focusTick={anTick} />
              {/* пометки — тут же, под опросником (09.10, Олег: «в той же вкладке Anamneza»):
                  врач заполняет анамнез и ставит пометки в одном месте */}
              <AlertsCard card={card} a={a} withAnamneza={false} />
            </div>
          </div>
        )}
      </div>
      <AppointDialog open={booking} name={card.name} appoint={card.appoint} a={a} onClose={() => setBooking(false)} />
      {toast && <Toast tone={toast.tone} text={toast.text} onClose={closeToast} />}
    </section>
  )
}
