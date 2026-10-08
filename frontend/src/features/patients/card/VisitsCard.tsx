import { Icon } from '../../../components/Icon'
import { AppLink } from '../../../components/AppLink'
import type { PatientCard, Visit } from './card'

/* Ближайший визит своей карточкой и история — те же слова, что на старой
   странице; «следующий», «последний» и правило ссылки на дневник (заполнен /
   состоявшийся пустой / будущий) решает сервер. Вид истории по макету (08.10):
   визит — блок на сером фоне с датой, чипом состояния, услугой и врачом. */
const T = {
  next: 'Următoarea vizită',
  title: 'Istoric vizite',
  last: 'ultimele',
  empty: '— încă fără vizite —',
  consult: 'Consultație',
  invite: '+ Consultație',
  all: 'Vezi tot istoricul ›',
} as const

/** Тон чипа состояния визита — цвет смысла (слово — с сервера). */
const TONE: Record<string, string> = {
  done: 'ok', arrived: 'info', waiting: 'info', confirmed: 'info', scheduled: 'info',
  noshow: 'bad', cancelled: 'mute',
}

interface Props {
  card: PatientCard
  /** адрес дневника визита; без него — адрес сервера (страница из журнала) */
  hrefOf?: (v: Visit) => string
}

export function NextVisitCard({ card }: Props) {
  const n = card.hero.next
  if (!n) return null
  return (
    <div className="fcard dp-next">
      <h3>{T.next}</h3>
      <div className="dp-next-when">{n.date} · {n.time}</div>
      <div className="dp-next-what">{n.service} · {n.doctor}</div>
    </div>
  )
}

export function VisitsCard({ card, hrefOf }: Props) {
  const hist = card.visits.history
  const href = (v: Visit) => (hrefOf ? hrefOf(v) : v.url)
  return (
    <div className="fcard">
      <h3>{T.title} <small>· {T.last} {hist.length}</small></h3>
      {hist.length ? (
        <div className="dp-vlist">
          {hist.map((v) => (
            <div key={v.id} className={`tline${v.is_next ? ' next' : ''}`}>
              <div className="tl-h">
                <span className="num">{v.when}</span>
                <span className={`chip ${TONE[v.status] ?? 'mute'}`}>{v.status_label}</span>
              </div>
              <b className="dp-tb-svc">{v.service}</b>
              <small>{v.doctor}</small>
              {v.consult === 'rec' && (
                <small className="dp-consult">
                  <Icon name="med" /> <AppLink href={href(v)}>{T.consult}</AppLink>{v.diag ? `: ${v.diag}` : ''}
                </small>
              )}
              {v.consult === 'invite' && <small><AppLink href={href(v)}>{T.invite}</AppLink></small>}
            </div>
          ))}
        </div>
      ) : <p className="hint dp-m0">{T.empty}</p>}
      <AppLink href={`/admin/search?q=${encodeURIComponent(card.name)}`} className="dp-hist-all">{T.all}</AppLink>
    </div>
  )
}
