import { DoctorCardScreen } from '../features/doctors/DoctorCardScreen'
import { DoctorsListScreen } from '../features/doctors/DoctorsListScreen'
import { PatientCardScreen } from '../features/patients/card/PatientCardScreen'
import { PatientsSearchScreen } from '../features/patients/PatientsSearchScreen'
import { BackupSettingsScreen } from '../features/settings/BackupSettingsScreen'
import { ClinicSettingsScreen, legacyUrl } from '../features/settings/ClinicSettingsScreen'
import { CryptSettingsScreen } from '../features/settings/CryptSettingsScreen'
import { FaqScreen } from '../features/settings/FaqScreen'
import { HoursSettingsScreen } from '../features/settings/HoursSettingsScreen'
import { LanSettingsScreen } from '../features/settings/LanSettingsScreen'
import { SecuritySettingsScreen } from '../features/settings/SecuritySettingsScreen'
import { ServicesSettingsScreen } from '../features/settings/ServicesSettingsScreen'
import { SystemSettingsScreen } from '../features/settings/SystemSettingsScreen'
import { SettingsHubScreen } from '../features/settings/SettingsHubScreen'
import { ThemeSettingsScreen } from '../features/settings/ThemeSettingsScreen'
import { StatsScreen } from '../features/stats/StatsScreen'
import { VisitScreen } from '../features/visits/VisitScreen'
import { OdontogramScreen } from '../features/clinical/OdontogramScreen'
import { PerioScreen } from '../features/clinical/PerioScreen'
import { DashScreen } from '../features/schedule/DashScreen'
import { DayScreen } from '../features/schedule/DayScreen'
import { WeekScreen } from '../features/schedule/WeekScreen'

/**
 * Корень клиента: развилка по имени экрана, которое сервер положил в
 * data-screen (тот же рубильник, что флаг в clinic.json). Экраны приезжают
 * по одному — см. docs/dentpilot-2/tasks.md, блок C.
 */
interface AppProps {
  screen: string
  /** Параметры экрана из data-params (id врача и т. п.). */
  params?: Record<string, string>
}

export function App({ screen, params = {} }: AppProps) {
  if (screen === 'settings_clinic') return <ClinicSettingsScreen />
  if (screen === 'doctors_list') return <DoctorsListScreen />
  if (screen === 'doctor_card') return <DoctorCardScreen dk={params.dk ?? ''} />
  if (screen === 'settings_hub') return <SettingsHubScreen />
  if (screen === 'settings_lan') return <LanSettingsScreen />
  if (screen === 'settings_faq') return <FaqScreen />
  if (screen === 'settings_hours') return <HoursSettingsScreen />
  if (screen === 'settings_services') return <ServicesSettingsScreen />
  if (screen === 'settings_theme') return <ThemeSettingsScreen />
  if (screen === 'settings_security') return <SecuritySettingsScreen />
  if (screen === 'settings_backup') return <BackupSettingsScreen />
  if (screen === 'settings_crypt') return <CryptSettingsScreen />
  if (screen === 'settings_system') return <SystemSettingsScreen />
  if (screen === 'stats') {
    return <StatsScreen from={params.from ?? ''} to={params.to ?? ''} />
  }
  if (screen === 'patients_search') return <PatientsSearchScreen params={params} />
  if (screen === 'patient_card') {
    return <PatientCardScreen pid={Number(params.pid)} views={params.views === '1'} />
  }
  if (screen === 'visit') return <VisitScreen aid={Number(params.aid)} back={params.back ?? ''} />
  if (screen === 'odontogram') {
    const t = params.t ? Number(params.t) : null
    return <OdontogramScreen pid={Number(params.pid)} t={Number.isInteger(t) ? t : null} />
  }
  if (screen === 'schedule_dash') return <DashScreen date={params.date ?? ''} />
  if (screen === 'schedule_week') return <WeekScreen date={params.date ?? ''} />
  if (screen === 'schedule_all') {
    return <DayScreen date={params.date ?? ''} f={params.f ?? ''} />
  }
  if (screen === 'schedule_doctor') {
    return <DayScreen date={params.date ?? ''} doctor={params.dk ?? ''} />
  }
  if (screen === 'perio') {
    const e = params.exam ? Number(params.exam) : null
    return <PerioScreen pid={Number(params.pid)} exam={Number.isInteger(e) ? e : null} />
  }
  return <UnknownScreen screen={screen} />
}

/**
 * Сервер отдал узел для экрана, которого в этом бандле нет (бандл старее
 * сервера или имя опечатано). Молчать нельзя — это выглядело бы как пустая
 * страница; называем экран и ведём на старую версию.
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
