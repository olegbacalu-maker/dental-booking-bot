import { useState } from 'react'
import { AppLink } from '../../../components/AppLink'
import { Icon, iconName } from '../../../components/Icon'
import type { Activity } from './card'

/* Летопись фиши: что с ней происходило. Просмотры (журнал доступа по
   195-му) по умолчанию спрятаны — рецепция открывает фишу десятки раз в
   день; по клику «accesările» лента дополняется ими, и адрес страницы
   получает ?views=1, как у старой страницы. */
const T = {
  title: 'Istoric activitate',
  sub: 'ce s-a întâmplat cu fișa',
  views: 'accesările',
  viewsTitle: 'Jurnalul accesărilor — cine și când a deschis fișa (Legea 195)',
  hideViews: 'ascunde accesările',
  all: 'Toate evenimentele',
  empty: '— încă fără evenimente —',
} as const

interface Props {
  activity: Activity
  onViews: (views: boolean) => void
}

export function ActivityCard({ activity, onViews }: Props) {
  const [all, setAll] = useState(false)
  const items = all ? activity.items : activity.items.slice(0, activity.shown)
  const rest = activity.items.length - activity.shown
  return (
    <div className="fcard">
      <h3>
        {T.title} <small>· {T.sub}</small> ·{' '}
        {activity.views
          ? <AppLink href="?" className="dp-views" onClick={(e) => { e.preventDefault(); onViews(false) }}>{T.hideViews}</AppLink>
          : <AppLink href="?views=1" className="dp-views" title={T.viewsTitle} onClick={(e) => { e.preventDefault(); onViews(true) }}>
              <Icon name="eye" /> {T.views}
            </AppLink>}
      </h3>
      {items.length ? items.map((it) => (
        <div key={it.id} className="acti">
          <span className="ai">{it.icon ? <Icon name={iconName(it.icon)} /> : '•'}</span>
          <div className="ab"><b>{it.text}</b><small>{it.when} · {it.who}</small></div>
          <span className="at">{it.hhmm}</span>
        </div>
      )) : <p className="hint dp-m0">{T.empty}</p>}
      {!all && rest > 0 && (
        <button type="button" className="actmore" onClick={() => setAll(true)}>
          {T.all} ({activity.items.length})
        </button>
      )}
    </div>
  )
}
