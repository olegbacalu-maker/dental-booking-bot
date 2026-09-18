import { Icon } from '../../components/Icon'
import type { DayCell, DayItem, DayModel } from './day'

/* Таблица дня: часы рядами, врачи колонками (C25.5a).

   Классы те же, что у старой страницы (.gridwrap, .grid, .hrow, .hour, .appt,
   .free, .goff, .stat), поэтому panel.css красит таблицу без единого нового
   правила, включая тему клиники.

   ⚠️ Экран пока ТОЛЬКО ЧИТАЕТ. Форма записи, модалки визита и переноса и само
   перетаскивание приезжают в C25.5b: договор перетаскивания живёт в panel.js
   и требует своей проверки, а половина договора хуже его отсутствия.
   Поэтому «+» здесь — ссылка на старую страницу с тем же часом, а не кнопка,
   которая ничего не делает. */
const T = {
  pause: 'pauză',
  closed: 'închis',
  busy: 'ocupat',
  hint: 'Programarea nouă și mutarea — deocamdată în varianta clasică.',
} as const

interface Props {
  model: DayModel
  /** Адрес старой страницы для «+» и для клика по записи. */
  legacy: string
}

export function DayGrid({ model, legacy }: Props) {
  return (
    <>
      <div className="gridwrap">
        <table className="grid">
          <tbody>
            <tr>
              <th className="gh-t" />
              {model.doctors.map((dc) => (
                <th key={dc.id}>
                  <a className="dh-n" href={`/admin/doctor/${dc.id}?date=${model.date}`}>{dc.name}</a>
                  <span className="dh-s">{dc.spec}</span>
                </th>
              ))}
            </tr>
            {model.hours.map((row) => (
              <tr key={row.h} className={`hrow${row.closed ? ' off' : ''}${row.now ? ' now' : ''}`}>
                <td className={`hour${row.closed ? ' off' : ''}${row.now ? ' now' : ''}`}>
                  {row.label}
                  {row.closed ? <small>{row.closed === 'pauza' ? T.pause : T.closed}</small> : null}
                </td>
                {row.cells.map((cell, i) => (
                  <Cell key={model.doctors[i]?.id ?? i} cell={cell}
                        href={`${legacy}${legacy.includes('?') ? '&' : '?'}time_pre=${row.label}#addform`} />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">{T.hint}</p>
    </>
  )
}

function Cell({ cell, href }: { cell: DayCell; href: string }) {
  if (cell.kind === 'off') return <td className="goff" />
  if (cell.kind === 'busy') {
    return (
      <td>
        <div className="appt busy"><Icon name="hourglass" /> {T.busy}</div>
      </td>
    )
  }
  if (cell.kind === 'free') {
    return <td><a className="free" href={href}>+</a></td>
  }
  return <td>{cell.items.map((x) => <Appt key={x.id} item={x} />)}</td>
}

function Appt({ item }: { item: DayItem }) {
  if (item.kind === 'note') {
    return (
      <div className="appt note" data-appt={item.id}>
        <Icon name="note" /> {item.time} {item.text}
      </div>
    )
  }
  return (
    <div className={`appt ${item.status}${item.urgent ? ' urgent' : ''}`} data-appt={item.id}>
      <b>{item.time} · {item.name}</b>
      {item.age ? <small className="dp-age"> {item.age} a.</small> : null}{' '}
      <Icon name={item.source === 'bot' ? 'bot' : 'pen'} />
      <br />
      {item.urgent ? <><Icon name="sos" /> </> : null}{item.service}{' '}
      <small>({item.dur}′)</small>
      <br /><small>{item.phone}</small>
      {item.status !== 'confirmed' && (
        <div className="stw"><span className={`stat s-${item.status}`}>{item.status_label}</span></div>
      )}
      {item.comment && <div className="cmt"><Icon name="chat" /> {item.comment}</div>}
    </div>
  )
}
