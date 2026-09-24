import { useEffect, type ReactNode } from 'react'
import { Outlet, useParams, useRouteError, type DataRouter, type RouteObject } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { AppShell } from '../layouts/AppShell'
import type { ShellModel } from '../layouts/shell'
import { DoctorCardScreen } from '../features/doctors/DoctorCardScreen'
import { DoctorsListScreen } from '../features/doctors/DoctorsListScreen'
import { PatientCardScreen } from '../features/patients/card/PatientCardScreen'
import { PatientsSearchScreen } from '../features/patients/PatientsSearchScreen'
import { BackupSettingsScreen } from '../features/settings/BackupSettingsScreen'
import { ClinicSettingsScreen } from '../features/settings/ClinicSettingsScreen'
import { CryptSettingsScreen } from '../features/settings/CryptSettingsScreen'
import { FaqScreen } from '../features/settings/FaqScreen'
import { HoursSettingsScreen } from '../features/settings/HoursSettingsScreen'
import { LanSettingsScreen } from '../features/settings/LanSettingsScreen'
import { SecuritySettingsScreen } from '../features/settings/SecuritySettingsScreen'
import { ServicesSettingsScreen } from '../features/settings/ServicesSettingsScreen'
import { SystemSettingsScreen } from '../features/settings/SystemSettingsScreen'
import { SettingsHubScreen, settingsHubRoute } from '../features/settings/SettingsHubScreen'
import { ThemeSettingsScreen } from '../features/settings/ThemeSettingsScreen'
import { StatsScreen } from '../features/stats/StatsScreen'
import { VisitScreen } from '../features/visits/VisitScreen'
import { OdontogramScreen } from '../features/clinical/OdontogramScreen'
import { PerioScreen } from '../features/clinical/PerioScreen'
import { DashScreen } from '../features/schedule/DashScreen'
import { DayScreen } from '../features/schedule/DayScreen'
import { WeekScreen } from '../features/schedule/WeekScreen'
import { QuickFind } from '../features/quickfind/QuickFind'
import { legacyUrl } from '../utils/legacy'
import { ROUTES, type ScreenName } from './routes'

/**
 * Корень клиента (B2 перехода к SPA): экран выбирает РОУТЕР по адресу, а не
 * развилка по `data-screen`. Таблица адресов — `routes.ts`, производная от
 * серверной (`scripts/screen_map.py`); своей здесь нет и быть не должно.
 * Решение и ступени — docs/dentpilot-2/spa-transition.md.
 */

/** Что сервер положил в узел монтирования. */
export interface MountNode {
  /** `data-screen`: какой экран сервер отдал по ЭТОМУ адресу. */
  screen: string
  /** `data-params`: параметры экрана, посчитанные сервером (дата по умолчанию и т. п.). */
  params: Record<string, string>
  /** `data-shell`: модель оболочки (B1); `null` — каркас печатает сервер. */
  shell: ShellModel | null
}

type Draw = (p: Record<string, string>) => ReactNode

function intOrNull(v: string | undefined): number | null {
  const n = v ? Number(v) : null
  return Number.isInteger(n) ? n : null
}

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
  stats: (p) => <StatsScreen from={p.from ?? ''} to={p.to ?? ''} />,
  patients_search: (p) => <PatientsSearchScreen params={p} />,
  patient_card: (p) => <PatientCardScreen pid={Number(p.pid)} views={p.views === '1'} />,
  // ⚠️ Параметр пути — `appt_id`, как у сервера. Ключ узла `aid` здесь больше
  // не читается: адрес визита разбирает роутер, а имена у них РАЗНЫЕ.
  visit: (p) => <VisitScreen aid={Number(p.appt_id)} back={p.back ?? ''} />,
  odontogram: (p) => <OdontogramScreen pid={Number(p.pid)} t={intOrNull(p.t)} />,
  schedule_dash: (p) => <DashScreen date={p.date ?? ''} dayLabel={p.day_label ?? ''} />,
  schedule_week: (p) => <WeekScreen date={p.date ?? ''} />,
  schedule_all: (p) => <DayScreen date={p.date ?? ''} f={p.f ?? ''} />,
  // ⛔ Не путать с doctor_card: тот же `dk`, но это день врача в журнале.
  schedule_doctor: (p) => <DayScreen date={p.date ?? ''} doctor={p.dk ?? ''} />,
  perio: (p) => <PerioScreen pid={Number(p.pid)} exam={intOrNull(p.exam)} />,
}

/**
 * Экраны, чьи данные грузит РОУТЕР (B2.2): загрузчик и первый кадр на время
 * ожидания. Остальные грузят сами (`useLoad`), пока не дошла их очередь.
 * ⛔ Загрузчик без `hydrateFallbackElement` не заводить: роутер нарисовал бы
 * вместо корня `null`, и оболочка пропала бы вместе с экраном (loader_hold.py).
 */
const ROUTE_DATA: Partial<Record<ScreenName, Pick<RouteObject, 'loader' | 'hydrateFallbackElement'>>> = {
  settings_hub: settingsHubRoute,
}

/**
 * Экран маршрута. ⭐ Сервер остаётся СВИДЕТЕЛЕМ: `data-screen` говорит, что он
 * отдал по этому адресу, и расхождение с роутером — это бандл и сервер из
 * разных версий. Показать тогда «чужой» экран с чужими параметрами было бы
 * хуже, чем честно сказать, что экрана нет.
 * ⚠️ Узел описывает ДОКУМЕНТ, то есть адрес первой загрузки. Переходы без
 * перезагрузки (B4) на нём не построить: параметры другого адреса принесут
 * загрузчики второй половины B2.
 */
function Screen({ name, node }: { name: ScreenName; node: MountNode }) {
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

/** Каркас: модель есть — оболочка наша (B1), нет — экран монтируется один. */
function Frame({ shell }: { shell: ShellModel | null }) {
  return shell ? <AppShell m={shell}><Outlet /></AppShell> : <Outlet />
}

/**
 * Дерево маршрутов. Оболочка — layout-маршрут, экраны — его дети, и ловушка
 * ошибок стоит МЕЖДУ ними: упавший экран оставляет сайдбар и шапку на месте.
 */
export function appRoutes(node: MountNode): RouteObject[] {
  return [{
    element: <Frame shell={node.shell} />,
    children: [{
      errorElement: <ScreenFailed />,
      children: [
        ...ROUTES.map((r) => ({
          path: r.path,
          element: <Screen name={r.screen} node={node} />,
          ...ROUTE_DATA[r.screen],
        })),
        { path: '*', element: <UnknownScreen screen={node.screen} /> },
      ],
    }],
  }]
}

export function App({ router }: { router: DataRouter }) {
  /* ⭐ Быстрый поиск живёт РЯДОМ с роутером, а не внутри экрана: Ctrl+K обязан
     работать откуда угодно, а накладка `position: fixed` накрывает окно
     независимо от того, где в разметке стоит узел React. */
  return (
    <>
      <RouterProvider router={router} />
      <QuickFind />
    </>
  )
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
