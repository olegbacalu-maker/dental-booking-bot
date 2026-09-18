import { Icon } from '../../../components/Icon'
import type { PatientCard } from './card'

/* Ближайший визит своей карточкой и история — те же слова, что на старой
   странице; «следующий», «последний» и правило ссылки на дневник (заполнен /
   состоявшийся пустой / будущий) решает сервер. */
const T = {
  next: 'Următoarea vizită',
  title: 'Istoric vizite',
  last: 'ultimele',
  empty: '— încă fără vizite —',
  consult: 'Consultație',
  invite: '+ Consultație',
  all: 'Vezi tot istoricul ›',
} as const

interface Props {
  card: PatientCard
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

export function VisitsCard({ card }: Props) {
  const hist = card.visits.history
  return (
    <div className="fcard">
      <h3>{T.title} <small>· {T.last} {hist.length}</small></h3>
      {hist.length ? hist.map((v) => (
        <div key={v.id} className={`tline${v.is_next ? ' next' : ''}`}>
          <div className="tdot"><i></i></div>
          <div className="tb">
            <small>{v.when} · {v.status_label}</small>
            <b className="dp-tb-svc">{v.service}</b>
            <small>{v.doctor}</small>
            {v.consult === 'rec' && (
              <small className="dp-consult">
                <Icon name="med" /> <a href={v.url}>{T.consult}</a>{v.diag ? `: ${v.diag}` : ''}
              </small>
            )}
            {v.consult === 'invite' && <small><a href={v.url}>{T.invite}</a></small>}
          </div>
        </div>
      )) : <p className="hint dp-m0">{T.empty}</p>}
      <a href={`/admin/search?q=${encodeURIComponent(card.name)}`} className="dp-hist-all">{T.all}</a>
    </div>
  )
}
