import { Icon, iconName } from '../../components/Icon'
import { AppLink } from '../../components/AppLink'
import { LoadFailed } from '../../components/LoadFailed'
import { defaultNavigate } from '../../hooks/useLoad'
import { useRouteLoad, type RouteLoad } from '../../hooks/useRouteLoad'
import { settings, type FaqData } from './settings'

const T = {
  title: 'Întrebări frecvente',
  hintA: 'Apăsați pe o întrebare pentru răspuns. Nu găsiți răspunsul? Scrieți-ne la ',
} as const

interface Props {
  navigate?: (url: string) => void
}

/** Данные экрана грузит роутер (B2.2), App.tsx › LOADS. */
export const loadFaq: RouteLoad<FaqData> = (signal) => settings.faq(signal)

/**
 * Справка директора. Вопросы и ответы — текст сервера (тот же, что на старой
 * странице; ответы с иконками приходят HTML-ом): справка версионируется тем
 * же коммитом, что и поведение, о котором рассказывает. Никакого JS в
 * раскрытии: <details> раскрывает браузер.
 */
export function FaqScreen({ navigate = defaultNavigate }: Props) {
  const { state, retry } = useRouteLoad<FaqData>(navigate)

  if (state.status === 'leaving') return null
  const head = <h2><Icon name="help" /> {T.title}</h2>
  if (state.status === 'failed') {
    return <section className="dp-react-root">{head}<LoadFailed error={state.error} onRetry={retry} /></section>
  }
  const data = state.status === 'ready' ? state.data : null
  return (
    <section className="dp-react-root" aria-busy={data === null}>
      {head}
      {data && (
        <>
          <p className="hint" style={{ marginTop: 0 }}>
            {T.hintA}<AppLink href={`mailto:${data.contact}`}>{data.contact}</AppLink>.
          </p>
          {data.items.map((it) => (
            <details key={it.question} className="faq dp-faq">
              <summary className="dp-faq-q"><Icon name={iconName(it.icon)} /> {it.question}</summary>
              <div className="dp-faq-a" dangerouslySetInnerHTML={{ __html: it.answer }} />
            </details>
          ))}
        </>
      )}
    </section>
  )
}
