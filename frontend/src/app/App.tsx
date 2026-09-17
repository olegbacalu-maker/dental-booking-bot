import { DoctorCardScreen } from '../features/doctors/DoctorCardScreen'
import { DoctorsListScreen } from '../features/doctors/DoctorsListScreen'
import { BackupSettingsScreen } from '../features/settings/BackupSettingsScreen'
import { ClinicSettingsScreen, legacyUrl } from '../features/settings/ClinicSettingsScreen'
import { FaqScreen } from '../features/settings/FaqScreen'
import { HoursSettingsScreen } from '../features/settings/HoursSettingsScreen'
import { LanSettingsScreen } from '../features/settings/LanSettingsScreen'
import { SecuritySettingsScreen } from '../features/settings/SecuritySettingsScreen'
import { ServicesSettingsScreen } from '../features/settings/ServicesSettingsScreen'
import { SettingsHubScreen } from '../features/settings/SettingsHubScreen'
import { ThemeSettingsScreen } from '../features/settings/ThemeSettingsScreen'

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
