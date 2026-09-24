import { Icon, iconName } from '../../components/Icon'
import { LoadFailed } from '../../components/LoadFailed'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { settings, type HintPart, type HubData } from './settings'

const T = {
  panel: 'Panou',
  title: 'Setări',
  sub: 'Alegeți o secțiune — modificările se aplică imediat, fără repornire',
} as const

/** Данные хаба грузит РОУТЕР (B2.2): запрос уходит при выборе маршрута. */
export const loadSettingsHub: RouteLoad<HubData> = (signal) => settings.hub(signal)

/** Хаб настроек: плитки с живой строкой состояния. Состояние считает сервер
 *  (обновление, BitLocker, шифрование, бот, сеть) — здесь только раскладка. */
export function SettingsHubScreen() {
  const { state, retry } = useRouteLoad<HubData>()

  if (state.status === 'leaving') return null
  const nav = (
    <div className="nav"><a href="/admin"><Icon name="home" /> {T.panel}</a></div>
  )
  if (state.status === 'failed') {
    return <section className="dp-react-root">{nav}<LoadFailed error={state.error} onRetry={retry} /></section>
  }
  const tiles = state.status === 'ready' ? state.data.tiles : []
  return (
    <section className="dp-react-root" aria-busy={state.status !== 'ready'}>
      {nav}
      <div className="pl-head"><div><h2>{T.title}</h2><p>{T.sub}</p></div></div>
      <div className="pl-tiles set-hub">
        {tiles.map((t) => (
          <a key={t.href} className="pl-tile" href={t.href}>
            <span className={`ico ${t.tone}`}><Icon name={iconName(t.icon)} /></span>
            <div className="pl-tv">
              <span>{t.label}</span>
              <small><Hint parts={t.hint} /></small>
            </div>
          </a>
        ))}
      </div>
    </section>
  )
}

/** Строка состояния плитки из кусков — та же разметка, что у layout._hint_html. */
function Hint({ parts }: { parts: HintPart[] }) {
  return (
    <>
      {parts.map((p, i) => {
        if (p.dot) return <span key={i} className="th-dot" style={{ background: p.dot }} />
        const inner = (
          <>
            {p.icon && <Icon name={iconName(p.icon)} />}
            {p.icon ? ` ${p.t ?? ''}` : p.t}
          </>
        )
        if (p.tone) return <b key={i} className={`dp-tone-${p.tone}`}>{inner}</b>
        return <span key={i}>{inner}</span>
      })}
    </>
  )
}
