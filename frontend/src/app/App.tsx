import { useCallback, useEffect, useLayoutEffect, useRef, type ReactNode } from 'react'
import {
  Outlet, ScrollRestoration, useLoaderData, useLocation, useNavigationType, useParams, useRouteError,
  useRouteLoaderData,
  type DataRouter, type GetScrollRestorationKeyFunction, type HydrationState,
  type LoaderFunctionArgs, type RouteObject, type ShouldRevalidateFunction,
} from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { AppShell } from '../layouts/AppShell'
import { DoctorCardScreen, loadDoctorCard } from '../features/doctors/DoctorCardScreen'
import { DoctorsListScreen, loadDoctorsList } from '../features/doctors/DoctorsListScreen'
import { loadPatientCard, PatientCardScreen } from '../features/patients/card/PatientCardScreen'
import { loadPatientsSearch, PatientsSearchScreen } from '../features/patients/PatientsSearchScreen'
import { BackupSettingsScreen, loadBackupSettings } from '../features/settings/BackupSettingsScreen'
import { ClinicSettingsScreen, loadClinicSettings } from '../features/settings/ClinicSettingsScreen'
import { CryptSettingsScreen, loadCryptSettings } from '../features/settings/CryptSettingsScreen'
import { FaqScreen, loadFaq } from '../features/settings/FaqScreen'
import { HoursSettingsScreen, loadHoursSettings } from '../features/settings/HoursSettingsScreen'
import { LanSettingsScreen, loadLanSettings } from '../features/settings/LanSettingsScreen'
import { ChairScreen, loadChair } from '../features/schedule/ChairScreen'
import { loadSecuritySettings, SecuritySettingsScreen } from '../features/settings/SecuritySettingsScreen'
import { loadServicesSettings, ServicesSettingsScreen } from '../features/settings/ServicesSettingsScreen'
import { loadSystemSettings, SystemSettingsScreen } from '../features/settings/SystemSettingsScreen'
import { loadSettingsHub, SettingsHubScreen } from '../features/settings/SettingsHubScreen'
import { loadThemeSettings, ThemeSettingsScreen } from '../features/settings/ThemeSettingsScreen'
import { loadStats, StatsScreen } from '../features/stats/StatsScreen'
import { loadVisit, VisitScreen } from '../features/visits/VisitScreen'
import { loadOdontogram, OdontogramScreen } from '../features/clinical/OdontogramScreen'
import { loadPerio, PerioScreen } from '../features/clinical/PerioScreen'
import { DashScreen, loadDash } from '../features/schedule/DashScreen'
import { DayScreen, loadDay } from '../features/schedule/DayScreen'
import { loadWeek, WeekScreen } from '../features/schedule/WeekScreen'
import { QuickFind } from '../features/quickfind/QuickFind'
import { defaultNavigate } from '../hooks/useLoad'
import { screenRoute, type ScreenData } from '../hooks/useRouteLoad'
import { fetchDoc } from '../services/doc'
import { legacyUrl } from '../utils/legacy'
import { applyHead, type MountNode } from './doc'
import { ROUTES, type ScreenName } from './routes'

export type { MountNode } from './doc'

/**
 * Корень клиента (B2 перехода к SPA): экран выбирает РОУТЕР по адресу, а не
 * развилка по `data-screen`. Таблица адресов — `routes.ts`, производная от
 * серверной (`scripts/screen_map.py`); своей здесь нет и быть не должно.
 * Решение и ступени — docs/dentpilot-2/spa-transition.md.
 */

type Draw = (p: Record<string, string>) => ReactNode

/**
 * Экран по имени. ⭐ `Record<ScreenName, …>`: имя, появившееся в карте и не
 * получившее здесь строки, — ошибка tsc, а не «экран не существует» у клиники.
 * Параметры пути приходят от роутера и перекрывают узел.
 */
export const SCREENS: Record<ScreenName, Draw> = {
  settings_clinic: () => <ClinicSettingsScreen />,
  doctors_list: () => <DoctorsListScreen />,
  doctor_card: (p) => <DoctorCardScreen dk={p.dk ?? ''} />,
  settings_hub: () => <SettingsHubScreen />,
  settings_lan: () => <LanSettingsScreen />,
  settings_faq: () => <FaqScreen />,
  settings_hours: () => <HoursSettingsScreen />,
  settings_services: () => <ServicesSettingsScreen />,
  settings_theme: () => <ThemeSettingsScreen />,
  settings_security: () => <SecuritySettingsScreen />,
  settings_backup: () => <BackupSettingsScreen />,
  settings_crypt: () => <CryptSettingsScreen />,
  settings_system: () => <SystemSettingsScreen />,
  stats: () => <StatsScreen />,
  patients_search: () => <PatientsSearchScreen />,
  patient_card: (p) => <PatientCardScreen pid={Number(p.pid)} />,
  // ⚠️ Параметр пути — `appt_id`, как у сервера. Ключ узла `aid` здесь больше
  // не читается: адрес визита разбирает роутер, а имена у них РАЗНЫЕ. `back`
  // загрузчик берёт из АДРЕСА (B2.3), экран показывает только эхо сервера.
  visit: (p) => <VisitScreen aid={Number(p.appt_id)} />,
  // `?t=` (зуб в фокус) экран читает из АДРЕСА сам (B4.3); узел его ещё шлёт.
  odontogram: (p) => <OdontogramScreen pid={Number(p.pid)} />,
  // ⛔ Панель параметров узла не читает: день берёт из АДРЕСА сама, шапку — из
  // эха живого канала. День из узла застывал на моменте загрузки документа.
  schedule_dash: () => <DashScreen />,
  schedule_week: () => <WeekScreen />,
  schedule_all: () => <DayScreen />,
  // ⛔ Не путать с doctor_card: тот же `dk`, но это день врача в журнале.
  schedule_doctor: (p) => <DayScreen doctor={p.dk ?? ''} />,
  perio: (p) => <PerioScreen pid={Number(p.pid)} />,
  // Экран «у кресла»: врача берёт из АДРЕСА загрузчик (`?doctor=`), не узел.
  chair: () => <ChairScreen />,
}

/**
 * Экраны, чьи данные грузит РОУТЕР (B2.2). Остальные грузят сами (`useLoad`),
 * пока не дошла их очередь. Маршрут собирает `screenRoute`: загрузчик без
 * первого кадра на время ожидания там собрать нельзя.
 */
const LOADS: Partial<Record<ScreenName, ScreenData>> = {
  settings_hub: loadSettingsHub,
  settings_faq: loadFaq,
  settings_backup: loadBackupSettings,
  settings_lan: loadLanSettings,
  settings_crypt: loadCryptSettings,
  settings_hours: loadHoursSettings,
  settings_services: loadServicesSettings,
  settings_security: loadSecuritySettings,
  settings_system: loadSystemSettings,
  settings_theme: loadThemeSettings,
  doctors_list: loadDoctorsList,
  doctor_card: loadDoctorCard,
  odontogram: loadOdontogram,
  schedule_week: loadWeek,
  schedule_all: loadDay,
  schedule_doctor: loadDay,
  stats: loadStats,
  perio: loadPerio,
  patient_card: loadPatientCard,
  visit: loadVisit,
  patients_search: loadPatientsSearch,
  settings_clinic: loadClinicSettings,
  // ⭐ Панель: загрузчик добывает ПЕРВЫЙ ответ живого канала (B4); опрос — `useLive`.
  schedule_dash: loadDash,
  chair: loadChair,
}

/**
 * Имя корневого маршрута. Его данные — узел документа ТЕКУЩЕГО адреса (B4):
 * при загрузке окна — узел этой страницы, после перехода без перезагрузки —
 * узел документа нового адреса (`services/doc.ts`).
 */
export const DOC = 'doc'

/** Узел документа текущего адреса — где бы в дереве ни спросили. */
function useDoc(): MountNode {
  return useRouteLoaderData(DOC) as MountNode
}

/**
 * Первый кадр запроса не делает: узел приехал инлайном и отдаётся роутеру
 * готовым. ⛔ Без этого загрузчик корня на первом кадре пошёл бы за
 * документом, который уже на экране, и оболочка ждала бы сеть — ровно то
 * мигание, от которого уходил B1.
 */
export function appHydration(node: MountNode): HydrationState {
  return { loaderData: { [DOC]: node } }
}

/**
 * Когда перечитывать документ: сменился ПУТЬ — это другая страница со своей
 * оболочкой; сменилась плашка `?msg=` — она часть оболочки. ⛔ Листание,
 * отбор, период на том же пути — тот же документ: запрос ради прежней модели
 * был бы лишним на каждом щелчке, а повтор экрана оболочку не трогает.
 */
export const docChanged: ShouldRevalidateFunction = ({ currentUrl, nextUrl }) =>
  currentUrl.pathname !== nextUrl.pathname
  || currentUrl.searchParams.getAll('msg').join('|') !== nextUrl.searchParams.getAll('msg').join('|')

/**
 * Загрузчик корня: узел документа нового адреса. Всё, что не «React-страница
 * того же бандла», уходит ДОКУМЕНТОМ, и переход не завершается — окно
 * покажет то, что сервер отдал бы по этому адресу при полной загрузке.
 */
async function docLoader({ request }: LoaderFunctionArgs): Promise<MountNode> {
  const a = await fetchDoc(request.url, request.signal)
  if (a.kind === 'page') return a.node
  defaultNavigate(a.url)
  return new Promise<MountNode>(() => { /* документ уходит: кадр прежний до конца */ })
}

/**
 * Ключ позиции прокрутки — ПУТЬ: листание и отбор на том же пути пишут адрес
 * `replace` и остаются там, где были, а новый путь начинается сверху. С
 * ключом по записи истории каждый такой экран прыгал бы наверх на каждом
 * щелчке. ⚠️ Адрес с якорем — свой ключ: сохранённая позиция пути иначе
 * перебила бы якорь (`#addform`).
 */
const scrollKey: GetScrollRestorationKeyFunction = (loc) => (loc.hash ? loc.key : loc.pathname)

/**
 * Новый путь — СВЕРХУ, даже если на нём уже бывали. Ключ позиции — путь, и
 * роутер вернул бы на PUSH прежнюю позицию этого пути (25.09: панель после
 * недели открывалась на 6 px — там, где её оставили; пока панель ждала данные
 * пустой, это пряталось за нулевой высотой). Слой-эффект стоит ПОСЛЕ
 * `ScrollRestoration`, поэтому его слово последнее в том же кадре. «Назад»
 * (POP) и `replace` на том же пути (листание, отбор) — как решил роутер;
 * якорь — к якорю.
 */
function ScrollTop() {
  const { pathname, hash } = useLocation()
  const type = useNavigationType()
  const prev = useRef(pathname)
  useLayoutEffect(() => {
    if (type === 'PUSH' && pathname !== prev.current && !hash) window.scrollTo(0, 0)
    prev.current = pathname
  }, [pathname, hash, type])
  return null
}

/**
 * Экран маршрута. ⭐ Сервер остаётся СВИДЕТЕЛЕМ: `data-screen` говорит, что он
 * отдал по этому адресу, и расхождение с роутером — это бандл и сервер из
 * разных версий. Показать тогда «чужой» экран с чужими параметрами было бы
 * хуже, чем честно сказать, что экрана нет.
 * ⭐ Узел — документа ТЕКУЩЕГО адреса (B4), а не первой загрузки: после
 * перехода без перезагрузки свидетель и параметры узла — нового адреса.
 */
function Screen({ name }: { name: ScreenName }) {
  const node = useDoc()
  const path = useParams()
  const mismatch = name !== node.screen
  useEffect(() => {
    if (mismatch) {
      console.error(`DentPilot: адрес ${window.location.pathname} — экран «${name}», `
        + `а сервер отдал «${node.screen}»`)
    }
  }, [mismatch, name, node.screen])
  if (mismatch) return <UnknownScreen screen={node.screen} />
  const p: Record<string, string> = { ...node.params }
  for (const [k, v] of Object.entries(path)) if (v !== undefined) p[k] = v
  return SCREENS[name](p)
}

/**
 * Каркас: модель есть — оболочка наша (B1), нет — экран монтируется один.
 * ⭐ Оболочка НЕ пересоздаётся при переходе: тот же `AppShell` получает модель
 * нового документа, и React правит пункт меню и подпись на месте — сайдбар и
 * шапка не исчезают ни на кадр (B4).
 */
function Frame() {
  const node = useLoaderData() as MountNode
  /* Голова нового адреса — в момент показа его кадра, а не раньше: переход
     могут перебить, и тема чужого адреса не должна лечь на прежний экран. */
  useLayoutEffect(() => { if (node.head) applyHead(node.head) }, [node.head])
  const body = <><ScrollRestoration getKey={scrollKey} /><ScrollTop /><Outlet /></>
  return node.shell ? <AppShell m={node.shell}>{body}</AppShell> : body
}

/**
 * Дерево маршрутов. Оболочка — layout-маршрут, экраны — его дети, и ловушка
 * ошибок стоит МЕЖДУ ними: упавший экран оставляет сайдбар и шапку на месте.
 * Данные корня — узел документа (`DOC`); на первом кадре их отдаёт
 * `appHydration`, дальше — `docLoader` на каждой смене пути.
 */
export function appRoutes(): RouteObject[] {
  return [{
    id: DOC,
    loader: docLoader,
    shouldRevalidate: docChanged,
    element: <Frame />,
    children: [{
      errorElement: <ScreenFailed />,
      children: [
        ...ROUTES.map((r) => screenRoute(r.path, <Screen name={r.screen} />, LOADS[r.screen])),
        { path: '*', element: <UnknownHere /> },
      ],
    }],
  }]
}

export function App({ router }: { router: DataRouter }) {
  /* ⭐ Быстрый поиск живёт РЯДОМ с роутером, а не внутри экрана: Ctrl+K обязан
     работать откуда угодно, а накладка `position: fixed` накрывает окно
     независимо от того, где в разметке стоит узел React. Открывает фишу он
     ПЕРЕХОДОМ (B4.2) — роутером напрямую, раз вне его дерева. */
  const go = useCallback((url: string) => { void router.navigate(url) }, [router])
  return (
    <>
      <RouterProvider router={router} />
      <QuickFind navigate={go} />
    </>
  )
}

/** Адрес, которого роутер не знает: экран называется так, как его назвал сервер. */
function UnknownHere() {
  return <UnknownScreen screen={useDoc().screen} />
}

/**
 * Сервер отдал узел для экрана, которого в этом бандле нет (бандл старее
 * сервера, имя опечатано или адрес не знаком роутеру). Молчать нельзя — это
 * выглядело бы как пустая страница; называем экран и ведём на старую версию.
 */
function UnknownScreen({ screen }: { screen: string }) {
  return (
    <section className="dp-react-root">
      <div className="banner err" role="alert">
        Ecranul «{screen}» nu există în interfața nouă.{' '}
        <a href={legacyUrl()}>Deschideți varianta clasică</a>.
      </div>
    </section>
  )
}

/**
 * Экран упал при отрисовке. Без этой ловушки роутер показал бы свою страницу
 * ошибки — по-английски и со стеком, а до роутера React снимал всё дерево
 * вместе с оболочкой, и окно оставалось пустым.
 */
function ScreenFailed() {
  const err = useRouteError()
  useEffect(() => { console.error('DentPilot: экран упал при отрисовке', err) }, [err])
  return (
    <section className="dp-react-root">
      <div className="banner err" role="alert">
        Ecranul nu a putut fi afișat.{' '}
        <a href={legacyUrl()}>Deschideți varianta clasică</a>.
      </div>
    </section>
  )
}
