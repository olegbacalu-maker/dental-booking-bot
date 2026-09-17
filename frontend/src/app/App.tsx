import { ClinicSettingsScreen, legacyUrl } from '../features/settings/ClinicSettingsScreen'

/**
 * Корень клиента: развилка по имени экрана, которое сервер положил в
 * data-screen (тот же рубильник, что флаг в clinic.json). Экраны приезжают
 * по одному — см. docs/dentpilot-2/tasks.md, блок C.
 */
interface AppProps {
  screen: string
}

export function App({ screen }: AppProps) {
  if (screen === 'settings_clinic') return <ClinicSettingsScreen />
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
